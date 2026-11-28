# PEKKA Asset Mapping & Proportion Reference

Source of truth: Figma reference screenshot and exported SVGs in `public/`.
All original SVG files are rendered directly without redrawing paths or replacing artwork.

## 1. Exported SVG Assets

| Visual Element | File Path (`public/`) | URL Path | Intrinsic Size (`viewBox`) | Key Visual Details |
| :--- | :--- | :--- | :--- | :--- |
| **Left Eye** | `public/EYES left.svg` | `/EYES%20left.svg` | `182 x 203` (`0 0 182 203`) | Dark brow/socket (`#0A0C11`, stroke `#282530`, inner shadows) + pink eye (`#D13FB5`) with masked white specular blur (`filter1_f_26_206`). Top edge slopes down left-to-right. |
| **Right Eye** | `public/EYES right.svg` | `/EYES%20right.svg` | `182 x 203` (`0 0 182 203`) | Mirrored right socket (`#0A0C11`, stroke `#282530`) + pink eye (`#D13FB5`) with masked white highlight (`filter1_f_23_142`). Top edge slopes down right-to-left. |
| **Lower Central Armour Bevel** | `public/Lower central armour bevel.svg` | `/Lower%20central%20armour%20bevel.svg` | `235 x 149` (`0 0 235 149`) | Central lower trapezoid plate with vertical metallic dark gradient (`#202127` -> `#15171B` -> `#090B0E`), stroke `#292731`, and subtle top inner highlight. |
| **Lower Triangular Armour** | `public/Lower triangular armour • cleaned.svg` | `/Lower%20triangular%20armour%20%E2%80%A2%20cleaned.svg` | `489 x 135` (`0 0 489 135`) | Flanking left and right triangular lower faceplate plates (`opacity: 0.72`, gradient `#171A21` -> `#0A0C10`, stroke `#22212B`). |

## 2. Missing / Unsupplied Assets

- **Z sleeping particles**: No SVG asset exported for `Z` characters; rendered as crisp typographic `Z` glyphs positioned near the upper eye region with CSS keyframe animations.
- **Audio waveform & transcription strip**: No static SVG exported; waveform uses thin vertical animated bars (`AudioWaveform.jsx`) and bottom-strip typography (`Transcription.jsx` / `ExecutionStatus.jsx`) matching the `PEKKA • sucess` Figma reference.

## 3. Figma Proportions & State Appearance

| State | Container Dimensions (Target) | Border & Glow | Visible Elements |
| :--- | :--- | :--- | :--- |
| **SLEEPING** (`PEKKA • Sp...`) | `176px x 72px`, radius `18px` | Thin dim metallic purple (`#8A6D9A` / `rgba(164, 130, 184, 0.5)`), subtle ambient glow | Black faceplate (`#050507`), relaxed left & right eye SVGs centered, organic floating `Z` particles, subtle breathing motion. Lower armour hidden. |
| **LISTENING** (`PEKKA • Voice pill`) | `336px x 124px`, radius `22px` | Illuminated metallic purple (`#A982C4`), soft outer illumination | Black faceplate, full-scale left & right eye SVGs with independent subtle scanning & blinking, lower central bevel + flanking triangular armour anchored at bottom, bottom-left waveform + progressive live transcription strip. |
| **EXECUTING** | `336px x 124px`, radius `22px` | Illuminated metallic purple | Black faceplate, eyes + lower armour, waveform stopped, concise execution status text in bottom strip. |
| **SUCCESS** (`PEKKA • sucess`) | `336px x 124px`, radius `22px` | Bright green (`#7BFF70`), subtle green illumination & restrained pulse | Only border changes to green; pink eyes and faceplate unchanged; holds ~`1500ms`, then collapses smoothly to `SLEEPING`. |
