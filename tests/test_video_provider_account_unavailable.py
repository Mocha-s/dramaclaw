from __future__ import annotations


def test_video_account_unavailable_is_classified_without_provider_details():
    from novelvideo.generators.video_generator import NewApiVideoError, _safe_video_error_code

    error = NewApiVideoError(
        'DramaClawAPI submit failed: HTTP 503 - {"error":{"message":"video task account unavailable"}}',
        status_code=503,
    )

    assert _safe_video_error_code(error, "EGRESS_OPERATION_UNKNOWN") == (
        "VIDEO_PROVIDER_ACCOUNT_UNAVAILABLE"
    )
    assert "account unavailable" not in _safe_video_error_code(error, "")
