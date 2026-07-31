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
- ライブラリ：one-partition LTOと専用PGOを適用した`finiteVolume`、専用PGOを適用した`libOpenFOAM`
- 実行ファイル：配布版`interFoam`

allocator設定は次の値である。

```text
MALLOC_CONF=narenas:1,background_thread:false,dirty_decay_ms:-1,muzzy_decay_ms:-1,thp:always,metadata_thp:always
```

OpenFOAMコアPGOの64試行均衡比較では、候補構成の最良値が`1.026366`秒、中央値が`1.083511`秒だった。
同じ実行時設定でコアPGOを使わない構成の中央値は`1.105612`秒だった。
探索開始時の壁時計時間は約`1.339`秒だったため、最良値は約23%短い。

目標の`0.8`秒以下には到達していない。

## 測定結果

| 施策 | 試行 | 最良値 | 中央値 | 判定 |
|---|---:|---:|---:|---|
| finiteVolume no-interposition | 29 | 1.052375秒 | 1.117325秒 | 単独で小幅改善 |
| finiteVolume PGO | 10 | 1.095675秒 | 1.135917秒 | 単独版は棄却 |
| finiteVolume PGO＋no-interposition | 44 | 1.063047秒 | 1.118065秒 | 組合せ候補として採用 |
| isolated MPI＋single-arena THP | 28 | 1.050054秒 | 1.105497秒 | 現在の実行時候補 |
| finiteVolume one-partition LTO＋PGO | 30 | 1.035988秒 | 1.105298秒 | 低分散候補として採用 |
| OpenFOAMコアPGO | 40 | 1.026366秒 | 1.083511秒 | 現在の最速候補 |
| 物性・界面ライブラリPGO | 40 | 1.036543秒 | 1.078978秒 | 基準との差が0.6msのため不採用 |
| Pstream PGO（途中結果） | 21 | 1.033945秒 | 1.089543秒 | 43完了時点で停止、未確定 |
| 配布版interFoam | 18 | 1.049377秒 | 1.106812秒 | 実行ファイル候補 |
| interFoam PGO＋no-interposition | 12 | 1.070908秒 | 1.129088秒 | 棄却 |

異なる表の数値は測定時間帯が異なるため、絶対値を直接比較しない。
採否は同じstudy内の分布で判断した。

## 棄却した施策

ランク数、NUMA配置、別allocator、allreduceアルゴリズム、collated出力、RAMディスク、ログ抑制、MPI DVM再利用を試した。
これらは改善しないか、OpenMPIとOpenFOAMの実行モデルに適合しなかった。
MPI DVMは同一コンテナ内でもPMIx初期化が`Unreachable`で失敗した。

単純な実行ファイルLTOと実行ファイルPGOも、配布版`interFoam`を安定して上回らなかった。
finiteVolumeのPGOは、no-interpositionを有効にした状態でプロファイルを取り直した。
異なる制御フローで採取したプロファイルの流用は、GCCの`coverage-mismatch`で停止したため採用していない。

## 成果物

- `scripts/optimize_runtime.py`：数値アルゴリズムを固定したOptuna探索
- `scripts/build_finite_volume_pgo_nointerpose.sh`：計測用と適用用のfiniteVolumeビルド
- `scripts/run_finite_volume_pgo_nointerpose.sh`：ビルド、学習、プロファイル統合、再ビルド
- `scripts/build_interfoam_pgo_nointerpose.sh`：interFoam本体の比較用PGOビルド
- `scripts/build_openfoam_core_pgo.sh`：OpenFOAMコアのPGOビルド
- `scripts/run_openfoam_core_pgo.sh`：OpenFOAMコアの学習と再ビルド
- `scripts/build_physics_pgo.sh`：物性・界面ライブラリの比較用PGOビルド
- `scripts/build_pstream_pgo.sh`：Pstreamの比較用PGOビルド
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
  --library-modes native_core_pgo \
  --file-handlers uncollated
```

現在の候補ライブラリは次の順で生成する。

```bash
bash scripts/run_finite_volume_pgo_nointerpose.sh
bash scripts/build_finite_volume_pgo_one_partition.sh
bash scripts/run_openfoam_core_pgo.sh
```

## 残っている検証

`0.8`秒以下の再現可能な構成は未確定である。
探索は2026年8月1日に利用者の指示で停止した。
停止時点で最適化コンテナは動作していない。
Pstream比較は64試行中43試行を完了しており、再開時は同じstudyを継続するか、均衡比較を最初から実行する。

最終候補が決まった後、同じ初期条件と終了時刻で基準版と候補版を実行する。
その出力をVTUへ変換し、`scripts/compare_vtk_fields.py`で`U`、`p_rgh`、`alpha.water`を比較する。
この比較が完了するまで、「計算結果が変わらない」という条件は未検証として扱う。
