# AGENTS.md

AI エージェント（Claude Code / Codex など）向けの作業メモ。人向けの説明は README.md。

## プロジェクト

骨盤 CT から臀筋（中殿筋・小殿筋・大殿筋）を TotalSegmentator で分割し、
断面積（CSA）計測と 3D 再構成を行う研究用パイプライン。
[tha-santacruz/BayesianUNet](https://github.com/tha-santacruz/BayesianUNet)（GPL-3.0）からの派生で、
`train.py` / `predict.py` / `bayesian_unet/` などは元リポジトリの Potsdam UNet 部分。

- GitHub: `taichi-shimizu-ortho/hip-cross-sectional-area`（**公開リポジトリ**）
- 実行環境: macOS (Apple Silicon, MPS)、`uv` で管理。スクリプトは `uv run python <script>.py`

## データの置き場所（重要）

入力データと出力物はリポジトリの外、Dropbox に置く。

```
~/Dropbox/Hip_cross-sectional_area/
├── input/            入力（DICOM シリーズ）。読み取り専用として扱う
│   └── sampleDATA/
└── output/           パイプラインの出力すべて（NIfTI, seg/, mesh/, area/, viewer.html, 配布資料 pptx）
```

- パスは `Path.home()` からの相対で組み立てる。ユーザー名入りの絶対パス
  （`/Users/...`）をコードやコミットに書かない。
- Python のパスは [`hip_paths.py`](hip_paths.py) に集約してある
  （`DATA_ROOT`, `INPUT_DIR`, `OUTPUT_DIR`, `DICOM_DIR`, `CT`, `CT_PELVIS`, `SEG_DIR`, `SEG_THIGH_DIR`, `MESH_DIR`, `AREA_DIR`, `VIEWER`）。
  新しいスクリプトもここから import し、パスを直書きしない。
  JSON などの出力にパスを記録するときは `hip_paths.from_home()` で `~/...` 形式にする。
- 各スクリプトの引数の既定値はこれらのパス。別の場所を使うときだけ `--seg-dir` などで上書きする。
- 配布資料 `docs/zoom_handout/` の `src/build_pptx.ts` も同じ `output/` を基準にする
  （`handout.json` の `image` と `meta.output_dir` は `output/` からの相対パス）。
- リポジトリ内の `data/` と `sampleDATA/` は移行前の旧置き場。新しい出力をここに書かない。

## 患者データの扱い

- CT・マスク・メッシュ・計測値・それらを含む図や pptx はすべて患者由来データ。
  **リポジトリにコミット・push しない**（リポジトリは公開）。`.gitignore` を緩めない。
- `input/` の DICOM は変更・削除しない。
- 結果は研究用途のみ。セグメンテーションは臨床的に検証されていない。
