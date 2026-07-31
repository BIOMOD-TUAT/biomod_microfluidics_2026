# OpenFOAM実行時間の最適化記録

## 対象と制約

この探索は、`tgv100`上で`interFoam`の短時間実行を高速化する。

探索中の`endTime`は`1e-6`に固定し、各候補の壁時計時間をOptunaで反復測定した。
メッシュ、物理モデル、線形ソルバー、前処理、収束許容値は変更していない。
コンパイルでは`-ffp-contract=off`を維持し、`-ffast-math`を使用していない。

測定対象はOpenFOAMが出力する`ExecutionTime`ではなく、`mpirun`の起動から終了までの壁時計時間である。
最終候補を本番へ適用する前に、基準版と候補版のVTKフィールドを比較する必要がある。

## 現在の候補

2026年8月1日時点の最速構成は次のとおり。

- MPIランク数：24
- 配置：`--bind-to hwthread --map-by core`
- MPI通信：`pml=ob1`、`btl=self,vader`
- MPI起動：`plm=isolated`
- 分割：`scotch`
- ファイルハンドラー：`uncollated`
- allocator：jemalloc
- jemalloc設定：単一arena、THP有効
- ライブラリ：Broadwell向けLTO、no-interposition、専用PGOを適用した`finiteVolume`
- 実行ファイル：配布版`interFoam`

allocator設定は次の値である。

```text
MALLOC_CONF=narenas:1,background_thread:false,dirty_decay_ms:-1,muzzy_decay_ms:-1,thp:always,metadata_thp:always
```

64試行の均衡比較では、候補構成の最良値が`1.050054`秒、中央値が`1.105497`秒だった。
基準構成（通常のshared-memory MPIと標準jemalloc）の中央値は`1.130072`秒だった。

目標の`0.8`秒以下には到達していない。

## 測定結果

| 施策 | 試行 | 最良値 | 中央値 | 判定 |
|---|---:|---:|---:|---|
| finiteVolume no-interposition | 29 | 1.052375秒 | 1.117325秒 | 単独で小幅改善 |
| finiteVolume PGO | 10 | 1.095675秒 | 1.135917秒 | 単独版は棄却 |
| finiteVolume PGO＋no-interposition | 44 | 1.063047秒 | 1.118065秒 | 組合せ候補として採用 |
| isolated MPI＋single-arena THP | 28 | 1.050054秒 | 1.105497秒 | 現在の実行時候補 |
| 配布版interFoam | 18 | 1.049377秒 | 1.106812秒 | 実行ファイル候補 |
| interFoam PGO＋no-interposition | 12 | 1.070908秒 | 1.129088秒 | 棄却 |

異なる表の数値は測定時間帯が異なるため、絶対値を直接比較しない。
採否は同じstudy内の分布で判断した。

## 棄却した施策

ランク数、NUMA配置、別allocator、allreduceアルゴリズム、collated出力、RAMディスク、ログ抑制、MPI DVM再利用を試した。
これらは改善しないか、OpenMPIとOpenFOAMの実行モデルに適合しなかった。

単純な実行ファイルLTOと実行ファイルPGOも、配布版`interFoam`を安定して上回らなかった。
finiteVolumeのPGOは、no-interpositionを有効にした状態でプロファイルを取り直した。
異なる制御フローで採取したプロファイルの流用は、GCCの`coverage-mismatch`で停止したため採用していない。

## 成果物

- `scripts/optimize_runtime.py`：数値アルゴリズムを固定したOptuna探索
- `scripts/build_finite_volume_pgo_nointerpose.sh`：計測用と適用用のfiniteVolumeビルド
- `scripts/run_finite_volume_pgo_nointerpose.sh`：ビルド、学習、プロファイル統合、再ビルド
- `scripts/build_interfoam_pgo_nointerpose.sh`：interFoam本体の比較用PGOビルド
- `scripts/compare_vtk_fields.py`：基準版と候補版のVTU配列比較
- `scripts/monitor_optuna.sh`：studyの進捗確認
- `docker/Dockerfile`：jemalloc、tcmalloc、numactlの追加
- `cases/calc_base/system/decomposeParDict`：24ランク用分割設定

PGOライブラリやOptunaデータベースはマシン固有の生成物であり、Gitには含めない。

## 探索の実行

Dockerイメージを作成した後、次のコマンドで安全な探索を実行できる。

```bash
python3 scripts/optimize_runtime.py \
  --trials 64 \
  --end-time 1e-6 \
  --ranks 24 \
  --placements sequential_hwthread_bind \
  --transports shared_memory_isolated \
  --allocators jemalloc_single_arena_thp \
  --decomposition-methods scotch \
  --solvers interFoam \
  --library-modes native_fv_pgo_nointerpose \
  --file-handlers uncollated
```

PGOライブラリは次のコマンドで生成する。

```bash
bash scripts/run_finite_volume_pgo_nointerpose.sh
```

## 残っている検証

`0.8`秒以下の再現可能な構成は未確定である。
現在はfiniteVolumeのLTO分割とIPA解析を追加した候補をビルドしている。

最終候補が決まった後、同じ初期条件と終了時刻で基準版と候補版を実行する。
その出力をVTUへ変換し、`scripts/compare_vtk_fields.py`で`U`、`p_rgh`、`alpha.water`を比較する。
この比較が完了するまで、「計算結果が変わらない」という条件は未検証として扱う。
