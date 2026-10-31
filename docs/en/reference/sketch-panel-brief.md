<!-- lang-switch -->
**English** · [简体中文](../../zh/reference/sketch-panel-brief.md)

# Sketch Panel Brief

Every beat is classified before the sketch prompt is built. The classification decides what the storyboard model is told about the panel.

| Kind | Trigger | Panel text sent to the model |
|---|---|---|
| Normal | Default | Processed visual description |
| Black screen | Description contains 黑场 / 黑屏 / 画面全黑 / 切黑 | Flat black panel, no scenery, no characters |
| Title card | Description contains 屏幕出现文字 / 字幕 / 片名 / 片尾 / 事实卡 | Blank card, no readable text |
| Prop insert | No named character and at least one `[[prop]]` marker | Prop as the single subject; the prop reference image is attached for shape and scale |

Panels without a named character get a `[NO CHARACTERS]` prefix. If the description mentions people (crowd, passers-by, tourists, a man, a woman), the panel is marked `[UNNAMED PEOPLE ONLY]` instead and gray mannequins are allowed.

## Prop FORM anchors

Each prop line in the sketch prompt carries a short form anchor taken from the prop's description (first sentence, up to 80 characters, colors removed), for example `FORM: palm-sized irregular wooden tag, held in one hand`. This gives the sketch model the object's class and scale without leaking material detail.

## Per-beat sketch prompt

In the beat workbench, open **Sketch prompt** under the sketch panel.

- **Append** (default) adds your text after the processed description as `ADDITIONAL DIRECTION`.
- **Override** replaces the description. Character and prop markers are still read from the original visual description. An override also cancels an automatic black-screen or title-card classification, so you can correct a misdetection.

The preview below the editor shows the kind badges and the exact panel text that will be submitted. It is produced by the same code path as generation.

## Color words

The sketch stage removes color adjectives so marker colors stay unambiguous. Multi-character color words (`鲜红`, `深蓝`) are always removed; single-character colors are removed only with a `色` / `的` suffix, so place names such as 黄果树 and screen-state words such as 黑场 are preserved. Scene and prop names are protected automatically.

## Prop marker colors

Global props marked in beats receive a marker color automatically when sketches are generated or regenerated. Replanning props keeps the colors already assigned.
