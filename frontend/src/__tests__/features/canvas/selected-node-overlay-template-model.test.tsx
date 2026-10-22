// SPDX-License-Identifier: Elastic-2.0
// Copyright (c) 2026 ClaymoreLab
import { act, render, waitFor } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { dispatchNodeAction } from '@/features/canvas/application/nodeActionResult';
import { CANVAS_NODE_TYPES, type CanvasNode } from '@/features/canvas/domain/canvasNodes';
import { SelectedNodeOverlay } from '@/features/canvas/ui/SelectedNodeOverlay';
import { useCanvasStore } from '@/stores/canvasStore';

const submitFreezoneTemplateEdit = vi.hoisted(() => vi.fn());
const awaitTaskCompletion = vi.hoisted(() => vi.fn());
const waitForFreezoneImageModels = vi.hoisted(() => vi.fn());

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/features/canvas/ui/NodeActionToolbar', () => ({
  NodeActionToolbar: () => null,
}));

vi.mock('@/api/ops', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  submitFreezoneTemplateEdit,
}));

vi.mock('@/api/tasks', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  awaitTaskCompletion,
}));

vi.mock('@/lib/url-params', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readUrl: () => ({ project: 'proj-1', canvas: 'canvas-1' }),
}));

vi.mock('@/lib/queries/generation-credit-cost', () => ({
  useGenerationCreditCost: () => ({ data: undefined, error: null }),
}));

vi.mock('@/features/canvas/hooks/useFreezoneImageModels', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  waitForFreezoneImageModels,
}));

const CATALOG_MODEL = {
  catalogId: 'catalog-lingshan',
  id: 'LingShan-G2',
  providerId: 'newapi' as const,
  apiModel: 'LingShan-G2',
  label: 'LingShan-G2',
};

const JOB_REF = {
  task_key: 'tk-1',
  task_type: 'freezone_template_edit',
  job_id: 'job-1',
};

describe('SelectedNodeOverlay template-edit model selection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    waitForFreezoneImageModels.mockResolvedValue({
      models: [CATALOG_MODEL],
      isLoading: false,
      isFallback: false,
      error: null,
    });
    submitFreezoneTemplateEdit.mockResolvedValue(JOB_REF);
    awaitTaskCompletion.mockResolvedValue({ result: { output_url: '/static/out.png' } });

    const sourceNode: CanvasNode = {
      id: 'img-1',
      type: CANVAS_NODE_TYPES.imageEdit,
      position: { x: 0, y: 0 },
      data: { imageUrl: '/static/source.png', aspectRatio: '1:1' },
    } as CanvasNode;
    useCanvasStore.getState().setCanvasData([sourceNode], []);
  });

  it('submits the current catalog apiModel and catalogId for toolbar grid actions', async () => {
    let resolveCatalog: (catalog: {
      models: typeof CATALOG_MODEL[];
      isLoading: boolean;
      isFallback: boolean;
      error: Error | null;
    }) => void = () => undefined;
    waitForFreezoneImageModels.mockImplementationOnce(
      () => new Promise((resolve) => { resolveCatalog = resolve; }),
    );

    render(
      <ReactFlowProvider>
        <SelectedNodeOverlay />
      </ReactFlowProvider>,
    );

    act(() => {
      dispatchNodeAction({
        nodeId: 'img-1',
        action: 'run_grid_multi_camera',
        requestId: 'req-1',
      });
    });

    await waitFor(() => expect(waitForFreezoneImageModels).toHaveBeenCalledWith('proj-1'));
    expect(submitFreezoneTemplateEdit).not.toHaveBeenCalled();

    await act(async () => {
      resolveCatalog({
        models: [CATALOG_MODEL],
        isLoading: false,
        isFallback: false,
        error: null,
      });
    });

    await waitFor(() => expect(submitFreezoneTemplateEdit).toHaveBeenCalled());
    expect(submitFreezoneTemplateEdit).toHaveBeenCalledWith('proj-1', {
      sourceUrl: '/static/source.png',
      mode: 'multi_camera_nine_grid',
      prompt: 'nodeToolbar.gridMenu.multiCameraGrid',
      model: CATALOG_MODEL.apiModel,
      catalogId: CATALOG_MODEL.catalogId,
    });
    expect(awaitTaskCompletion).toHaveBeenCalledWith('tk-1', 'proj-1');
    await waitFor(() => {
      const resultNode = useCanvasStore.getState().nodes.find((node) => node.id !== 'img-1');
      expect(resultNode?.data).toMatchObject({
        imageUrl: '/static/out.png',
        previewImageUrl: '/static/out.png',
        isGenerating: false,
        generationError: null,
      });
    });
  });

  it('does not submit a toolbar grid action when the image catalog is empty', async () => {
    waitForFreezoneImageModels.mockResolvedValue({
      models: [],
      isLoading: false,
      isFallback: false,
      error: null,
    });
    render(
      <ReactFlowProvider>
        <SelectedNodeOverlay />
      </ReactFlowProvider>,
    );

    act(() => {
      dispatchNodeAction({
        nodeId: 'img-1',
        action: 'run_grid_plot_four',
        requestId: 'req-empty-catalog',
      });
    });

    await waitFor(() => {
      const resultNode = useCanvasStore.getState().nodes.find((node) => node.id !== 'img-1');
      expect(resultNode?.data).toMatchObject({
        generationError: '图片模型目录没有可用模型，无法提交宫格模板',
      });
    });
    expect(submitFreezoneTemplateEdit).not.toHaveBeenCalled();
  });

  it('does not submit a fallback model after the catalog request fails', async () => {
    waitForFreezoneImageModels.mockResolvedValue({
      models: [{ ...CATALOG_MODEL, id: 'newapi_gpt_image2', apiModel: 'newapi_gpt_image2' }],
      isLoading: false,
      isFallback: true,
      error: new Error('catalog unavailable'),
    });
    render(
      <ReactFlowProvider>
        <SelectedNodeOverlay />
      </ReactFlowProvider>,
    );

    act(() => {
      dispatchNodeAction({
        nodeId: 'img-1',
        action: 'run_grid_plot_four',
        requestId: 'req-catalog-error',
      });
    });

    await waitFor(() => {
      const resultNode = useCanvasStore.getState().nodes.find((node) => node.id !== 'img-1');
      expect(resultNode?.data).toMatchObject({
        generationError: '图片模型目录加载失败，请检查连接后重试',
      });
    });
    expect(submitFreezoneTemplateEdit).not.toHaveBeenCalled();
  });
});
