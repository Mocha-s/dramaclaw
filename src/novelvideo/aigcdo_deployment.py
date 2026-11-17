"""Explicit AIGCDO service composition for the CE host process."""

from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cryptography.fernet import Fernet

from novelvideo.aigcdo_application_keys import AigcdoApplicationKeys, AigcdoApplicationKeyStore
from novelvideo.aigcdo_billing import AigcdoBilling, CreditDisplayPolicy
from novelvideo.aigcdo_gateway import AigcdoGatewayClient
from novelvideo.aigcdo_payments import AigcdoPayments, AigcdoPaymentStore
from novelvideo.aigcdo_sessions import AigcdoAuthPort, AigcdoSessionStore
from novelvideo import aigcdo_model_runtime
from novelvideo.aigcdo_execution import AigcdoExecutionAuthority
from novelvideo.api.routes.aigcdo_auth import trusted_app_origin
from novelvideo.ports.aigcdo_project import AigcdoProjectAccess, AigcdoProjectRegistry
from novelvideo.ports.local.audit import NoOpAuditSink
from novelvideo.ports.registry import register_port
from novelvideo.shared import runtime_env

logger = logging.getLogger(__name__)


class AigcdoDeployment:
    auth_provider = "aigcdo"
    # The Agent is offered only where each user's worker can be isolated (see _agent_runtime).
    agent_ready = False

    @classmethod
    def from_env(cls) -> AigcdoDeployment:
        if not runtime_env.is_ce_effective():
            raise RuntimeError("AIGCDO requires CE without a control-plane DSN")
        if os.environ.get("DRAMACLAW_LOCAL_AGENT_TRUST", "").strip().lower() in {"1", "true", "yes", "on"}:
            raise RuntimeError("AIGCDO cannot enable local agent trust")
        names = (
            "AIGCDO_APP_ORIGIN", "AIGCDO_STATE_DIR", "AIGCDO_ENCRYPTION_KEY",
            "AIGCDO_APPLICATION_GROUP_ID", "AIGCDO_CREDITS_PER_USD",
            "AIGCDO_CREDIT_DECIMALS", "AIGCDO_CREDIT_POLICY_VERSION",
        )
        shared = [
            name for name in aigcdo_model_runtime.SHARED_CREDENTIAL_ENV
            # Cognee config exports the placeholder at import time, before this check runs.
            if os.environ.get(name, "").strip() not in {"", aigcdo_model_runtime.PLACEHOLDER_KEY}
        ]
        if shared:
            # A process-wide model key would be spent on every user's behalf.
            raise RuntimeError("AIGCDO forbids shared model credentials: " + ", ".join(shared))
        values = {name: os.environ.get(name, "").strip() for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise RuntimeError("Missing AIGCDO configuration: " + ", ".join(missing))
        try:
            origin = trusted_app_origin(values["AIGCDO_APP_ORIGIN"])
            state_dir = Path(values["AIGCDO_STATE_DIR"])
            if not state_dir.is_absolute() or state_dir == Path("/"):
                raise ValueError("state directory must be absolute")
            key = values["AIGCDO_ENCRYPTION_KEY"].encode("ascii")
            Fernet(key)
            group_id = int(values["AIGCDO_APPLICATION_GROUP_ID"])
            if group_id <= 0:
                raise ValueError("group must be positive")
            policy = CreditDisplayPolicy(
                Decimal(values["AIGCDO_CREDITS_PER_USD"]), int(values["AIGCDO_CREDIT_DECIMALS"]),
                values["AIGCDO_CREDIT_POLICY_VERSION"],
            )
            aigcdo_model_runtime._catalog.cache_clear()
            # Optional seed for the model list; the administrator's saved settings replace it.
            if os.environ.get(aigcdo_model_runtime.CATALOG_ENV, "").strip():
                aigcdo_model_runtime._catalog(os.environ[aigcdo_model_runtime.CATALOG_ENV].strip())
            aigcdo_model_runtime.embedding_endpoint()
        except (ValueError, InvalidOperation, UnicodeError):
            raise RuntimeError("Invalid AIGCDO deployment configuration") from None
        deployment = cls()
        deployment.origin = origin
        deployment.state_dir = state_dir
        deployment.gateway = AigcdoGatewayClient()
        deployment.auth = AigcdoAuthPort(AigcdoSessionStore(state_dir / "sessions.db", key), deployment.gateway)
        deployment.application_keys = AigcdoApplicationKeys(
            deployment.auth, AigcdoApplicationKeyStore(state_dir / "application-keys.db", key), group_id=group_id,
        )
        from novelvideo.api.routes.aigcdo_admin import AigcdoAdmin, stored_credit_policy

        try:
            deployment.admin = AigcdoAdmin(key)
        except ValueError:
            raise RuntimeError("Invalid AIGCDO deployment configuration") from None
        policy = stored_credit_policy(policy)  # the administrator's saved ratio beats the environment
        deployment.billing = AigcdoBilling(deployment.auth, policy)
        deployment.payments = AigcdoPayments(
            deployment.auth, AigcdoPaymentStore(state_dir / "payments.db", key), policy, origin,
        )
        deployment.projects = AigcdoProjectRegistry(deployment.auth.store)
        deployment.execution = AigcdoExecutionAuthority(
            deployment.auth, deployment.application_keys, deployment.projects,
            state_dir / "execution.db", key,
        )
        return deployment

    async def on_startup(self, *, register_as_worker: bool = False) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.state_dir.chmod(0o700)
        except OSError:
            raise RuntimeError("AIGCDO storage is unavailable") from None
        await self.gateway.__aenter__()
        reason = await asyncio.to_thread(self._agent_runtime)
        self.agent_ready = not reason
        if reason:
            logger.warning("AIGCDO Agent (chat) is disabled: %s", reason)

    @staticmethod
    def _agent_runtime() -> str:
        """Why Agent workers cannot run here, or "" when they can."""
        import subprocess
        import tempfile

        from novelvideo.chat.hermes_pool import _hermes_cli_path
        from novelvideo.security.sandbox_wrap import SandboxSpec, wrap_command

        if not aigcdo_model_runtime.agent_model():
            return "no Agent model is configured"
        cli = _hermes_cli_path()
        if not cli.exists():
            return "the Hermes CLI is not installed"
        try:
            # The real thing, once: the CLI must start inside one user's view of the host.
            with tempfile.TemporaryDirectory(prefix="aigcdo-agent-probe-") as home:
                argv = wrap_command(
                    [str(cli), "--version"], SandboxSpec(user="agent-probe", hermes_home=Path(home)),
                )
                result = subprocess.run(
                    argv, capture_output=True, timeout=120,
                    env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": home, "HERMES_HOME": home},
                )
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            return str(exc) or type(exc).__name__
        if result.returncode != 0:
            return "the Hermes CLI cannot start inside the per-user sandbox"
        return ""

    async def on_shutdown(self) -> None:
        await self.gateway.__aexit__(None, None, None)


def register_aigcdo_ports() -> None:
    from novelvideo.ports.local import LocalEgress
    from novelvideo.ports.local.credit_quote import LocalCreditQuote
    from novelvideo.ports.local.egress_operations import LocalEgressOperations
    from novelvideo.ports.local.release_feed import LocalReleaseFeed
    from novelvideo.ports.local.tasks import InlineTaskBackend, InMemoryCancellationStore
    from novelvideo.ports.local.usage import NoOpProviderInstrumentation, NoOpUsageMeter
    from novelvideo.ports.product_surface_access import LocalProductSurfaceAccess

    deployment = AigcdoDeployment.from_env()
    execution = deployment.execution
    for name, implementation in (
        # The existing task engine, signed and re-authorised per user; the gateway is the only ledger.
        ("task_backend", InlineTaskBackend(
            producer=execution, consumer=execution.consumer, run_scope=execution.task_run_scope,
        )),
        ("cancellation_store", InMemoryCancellationStore()),
        ("usage_meter", NoOpUsageMeter()),
        ("provider_instrumentation", NoOpProviderInstrumentation()),
        ("credit_quote", LocalCreditQuote()),
        ("release_feed", LocalReleaseFeed()),
        ("product_surface_access", LocalProductSurfaceAccess()),
        ("egress", LocalEgress()),
        ("egress_operations", LocalEgressOperations()),
        ("auth", deployment.auth),
        ("project_registry", deployment.projects),
        ("project_access", AigcdoProjectAccess(deployment.projects)),
        ("audit_sink", NoOpAuditSink()),
        ("lifecycle", deployment),
        ("auth_session", deployment.execution),
        ("authz", deployment.execution),
        ("model_credentials", deployment.execution),
        ("task_envelope_consumer", deployment.execution.consumer),
    ):
        register_port(name, implementation)
