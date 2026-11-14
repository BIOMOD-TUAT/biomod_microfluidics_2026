import os
import re
import glob
import gzip
import numpy as np
import pandas as pd
from tqdm import tqdm
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

# ==============================================================================
# 1. パス設定 (Dockerコンテナ内)
# ==============================================================================
SIM_RESULT_DIR = "/workspace/cases"
OUTPUT_DIR = "/workspace"


# ==============================================================================
# 2. OpenFOAM ASCII / Binary 自動判別パーサー
# ==============================================================================
def read_foam_raw(filepath):
    target_path = filepath
    if not os.path.exists(target_path):
        if os.path.exists(filepath + '.gz'):
            target_path = filepath + '.gz'
        else:
            return None, None
    try:
        if target_path.endswith('.gz'):
            with gzip.open(target_path, 'rb') as f:
                content = f.read()
        else:
            with open(target_path, 'rb') as f:
                content = f.read()
        
        header_text = content[:2000].decode('latin-1', errors='ignore')
        is_binary = ('format      binary;' in header_text) or ('format binary;' in header_text)
        return content, is_binary
    except Exception:
        return None, None

def parse_foam_scalar(filepath):
    content, is_binary = read_foam_raw(filepath)
    if content is None:
        return None

    text_head = content[:3000].decode('latin-1', errors='ignore')

    m_uni = re.search(r'internalField\s+uniform\s+([\d\.eE\+\-]+)\s*;', text_head)
    if m_uni:
        return float(m_uni.group(1))

    m_list = re.search(r'internalField\s+nonuniform\s+List<scalar>\s*(\d+)', text_head)
    if not m_list:
        return None

    num_elems = int(m_list.group(1))

    if not is_binary:
        text = content.decode('latin-1', errors='ignore')
        idx_start = text.find('(', m_list.end())
        idx_end = text.rfind(')')
        if idx_start != -1 and idx_end != -1:
            body = text[idx_start+1:idx_end]
            return np.fromstring(body, sep=' ')
        return None
    else:
        idx_start = content.find(b'(', m_list.end())
        if idx_start == -1:
            return None
        data_start = idx_start + 1
        while data_start < len(content) and content[data_start:data_start+1] in b'\r\n ':
            data_start += 1

        byte_len_64 = num_elems * 8
        if data_start + byte_len_64 <= len(content):
            arr = np.frombuffer(content[data_start:data_start+byte_len_64], dtype=np.float64)
            if len(arr) == num_elems and not np.isnan(arr[0]):
                return arr

        byte_len_32 = num_elems * 4
        if data_start + byte_len_32 <= len(content):
            arr = np.frombuffer(content[data_start:data_start+byte_len_32], dtype=np.float32).astype(np.float64)
            if len(arr) == num_elems and not np.isnan(arr[0]):
                return arr

        return None

def parse_foam_vector(filepath):
    content, is_binary = read_foam_raw(filepath)
    if content is None:
        return None

    text_head = content[:3000].decode('latin-1', errors='ignore')
    m_list = re.search(r'internalField\s+nonuniform\s+List<vector>\s*(\d+)', text_head)
    if not m_list:
        return None

    num_elems = int(m_list.group(1))

    if not is_binary:
        text = content.decode('latin-1', errors='ignore')
        idx_start = text.find('(', m_list.end())
        idx_end = text.rfind(')')
        if idx_start != -1 and idx_end != -1:
            body = text[idx_start+1:idx_end].replace('(', ' ').replace(')', ' ')
            arr = np.fromstring(body, sep=' ')
            return arr.reshape(-1, 3)
        return None
    else:
        idx_start = content.find(b'(', m_list.end())
        if idx_start == -1:
            return None
        data_start = idx_start + 1
        while data_start < len(content) and content[data_start:data_start+1] in b'\r\n ':
            data_start += 1

        byte_len_64 = num_elems * 24
        if data_start + byte_len_64 <= len(content):
            arr = np.frombuffer(content[data_start:data_start+byte_len_64], dtype=np.float64)
            if len(arr) == num_elems * 3:
                return arr.reshape(-1, 3)

        byte_len_32 = num_elems * 12
        if data_start + byte_len_32 <= len(content):
            arr = np.frombuffer(content[data_start:data_start+byte_len_32], dtype=np.float32).astype(np.float64)
            if len(arr) == num_elems * 3:
                return arr.reshape(-1, 3)

        return None

def parse_foam_points(filepath):
    content, is_binary = read_foam_raw(filepath)
    if content is None:
        return None

    text_head = content[:3000].decode('latin-1', errors='ignore')
    m = re.search(r'(?:List<vector>\s*)?(\d+)\s*\n*\(', text_head)
    if not m:
        return None

    num_elems = int(m.group(1))

    if not is_binary:
        text = content.decode('latin-1', errors='ignore')
        idx_start = text.find('(', m.end()-2)
        idx_end = text.rfind(')')
        if idx_start != -1 and idx_end != -1:
            body = text[idx_start+1:idx_end].replace('(', ' ').replace(')', ' ')
            arr = np.fromstring(body, sep=' ')
            if len(arr) == num_elems * 3:
                return arr.reshape(-1, 3)
        return None
    else:
        idx_start = content.find(b'(', m.end()-2)
        if idx_start == -1:
            return None
        data_start = idx_start + 1
        while data_start < len(content) and content[data_start:data_start+1] in b'\r\n ':
            data_start += 1

        byte_len_64 = num_elems * 24
        if data_start + byte_len_64 <= len(content):
            arr = np.frombuffer(content[data_start:data_start+byte_len_64], dtype=np.float64)
            if len(arr) == num_elems * 3:
                return arr.reshape(-1, 3)

        byte_len_32 = num_elems * 12
        if data_start + byte_len_32 <= len(content):
            arr = np.frombuffer(content[data_start:data_start+byte_len_32], dtype=np.float32).astype(np.float64)
            if len(arr) == num_elems * 3:
                return arr.reshape(-1, 3)

        return None

def parse_foam_labels(filepath):
    content, is_binary = read_foam_raw(filepath)
    if content is None:
        return None

    text_head = content[:3000].decode('latin-1', errors='ignore')
    m = re.search(r'(?:List<label>\s*)?(\d+)\s*\n*\(', text_head)
    if not m:
        return None

    num_elems = int(m.group(1))

    if not is_binary:
        text = content.decode('latin-1', errors='ignore')
        idx_start = text.find('(', m.end()-2)
        idx_end = text.rfind(')')
        if idx_start != -1 and idx_end != -1:
            body = text[idx_start+1:idx_end]
            return np.fromstring(body, sep=' ', dtype=int)
        return None
    else:
        idx_start = content.find(b'(', m.end()-2)
        if idx_start == -1:
            return None
        data_start = idx_start + 1
        while data_start < len(content) and content[data_start:data_start+1] in b'\r\n ':
            data_start += 1

        byte_len_32 = num_elems * 4
        if data_start + byte_len_32 <= len(content):
            arr = np.frombuffer(content[data_start:data_start+byte_len_32], dtype=np.int32)
            if len(arr) == num_elems:
                return arr.astype(int)

        byte_len_64 = num_elems * 8
        if data_start + byte_len_64 <= len(content):
            arr = np.frombuffer(content[data_start:data_start+byte_len_64], dtype=np.int64)
            if len(arr) == num_elems:
                return arr.astype(int)

        return None

def compute_cell_centres_from_mesh(mesh_dir):
    points = parse_foam_points(os.path.join(mesh_dir, 'points'))
    owner = parse_foam_labels(os.path.join(mesh_dir, 'owner'))
    if points is None or owner is None:
        return None

    n_cells = np.max(owner) + 1
    neighbour_file = os.path.join(mesh_dir, 'neighbour')
    neighbour = parse_foam_labels(neighbour_file)
    if neighbour is not None and len(neighbour) > 0:
        n_cells = max(n_cells, np.max(neighbour) + 1)

    cell_sum = np.zeros((n_cells, 3))
    cell_count = np.zeros(n_cells)

    faces_file = os.path.join(mesh_dir, 'faces')
    content, is_binary = read_foam_raw(faces_file)

    if content is not None and not is_binary:
        text = content.decode('latin-1', errors='ignore')
        matches = re.findall(r'\d+\(([\d\s]+)\)', text)
        if len(matches) >= len(owner):
            for i, match in enumerate(matches[:len(owner)]):
                pts_idx = [int(x) for x in match.split()]
                face_center = np.mean(points[pts_idx], axis=0)
                c_owner = owner[i]
                cell_sum[c_owner] += face_center
                cell_count[c_owner] += 1
                if neighbour is not None and i < len(neighbour):
                    c_nei = neighbour[i]
                    cell_sum[c_nei] += face_center
                    cell_count[c_nei] += 1

            cell_count[cell_count == 0] = 1
            return cell_sum / cell_count[:, None]

    return None

mesh_centres_cache = {}

def get_cell_centres_cached(mesh_dir, time_dir=None):
    cache_key = mesh_dir
    if cache_key in mesh_centres_cache:
        return mesh_centres_cache[cache_key]

    if time_dir:
        c_file = os.path.join(time_dir, 'C')
        c_arr = parse_foam_vector(c_file)
        if c_arr is not None:
            mesh_centres_cache[cache_key] = c_arr
            return c_arr

    c_file = os.path.join(mesh_dir, 'C')
    c_arr = parse_foam_vector(c_file)
    if c_arr is not None:
        mesh_centres_cache[cache_key] = c_arr
        return c_arr

    centres = compute_cell_centres_from_mesh(mesh_dir)
    if centres is not None:
        mesh_centres_cache[cache_key] = centres
        return centres

    return None


# ==============================================================================
# 3. ドロップレット領域抽出 & S値計算（メッシュ情報も返却）
# ==============================================================================
def calculate_S_value(coords, alpha_vals, user_Nz=None):
    if len(coords) == 0 or len(alpha_vals) == 0:
        return 0.0, 1, (0.0, 0.0, 0.0)

    # 格子間隔・Z方向セル数 (Nz) の算出
    unique_z = np.unique(np.round(coords[:, 2], 6))
    Nz = user_Nz if user_Nz is not None else len(unique_z)
    if Nz == 0:
        Nz = 1

    # 格子間隔 (dx, dy, dz) の標準値を計測
    dx = float(np.min(np.diff(np.unique(np.round(coords[:, 0], 6))))) if len(np.unique(coords[:, 0])) > 1 else 0.0
    dy = float(np.min(np.diff(np.unique(np.round(coords[:, 1], 6))))) if len(np.unique(coords[:, 1])) > 1 else 0.0
    dz = float(np.min(np.diff(unique_z))) if len(unique_z) > 1 else 0.0
    mesh_info = (dx, dy, dz)

    mask = (coords[:, 0] > 0) & (alpha_vals > 0.5)
    filtered_coords = coords[mask]
    filtered_alpha = alpha_vals[mask]

    if len(filtered_coords) == 0:
        return 0.0, Nz, mesh_info

    if len(filtered_coords) == 1:
        return float(filtered_alpha[0]) / Nz, Nz, mesh_info

    tree = cKDTree(filtered_coords)
    dists, _ = tree.query(filtered_coords, k=min(5, len(filtered_coords)))

    if dists.shape[1] > 1:
        min_dist = np.median(dists[:, 1])
        r_thresh = max(min_dist * 1.8, 1e-8)
    else:
        r_thresh = 1e-4

    pairs = tree.query_pairs(r=r_thresh, output_type='ndarray')

    if len(pairs) == 0:
        return float(np.max(filtered_alpha)) / Nz, Nz, mesh_info

    n_samples = len(filtered_coords)
    adj = csr_matrix((np.ones(len(pairs), dtype=bool), (pairs[:, 0], pairs[:, 1])), shape=(n_samples, n_samples))
    _, labels = connected_components(csgraph=adj, directed=False)

    counts = np.bincount(labels)
    largest_label = np.argmax(counts)

    droplet_alpha_sum = np.sum(filtered_alpha[labels == largest_label])
    S_val = float(droplet_alpha_sum / Nz)

    return S_val, Nz, mesh_info


# ==============================================================================
# 4. 解析ループ処理
# ==============================================================================
def process_simulation_folders(root_dir):
    records = []
    mesh_summaries = {}  # ケースごとのメッシュ情報を保持

    if not os.path.exists(root_dir):
        print(f"[エラー] 指定されたパスが存在しません: {root_dir}")
        return pd.DataFrame(), mesh_summaries

    folders = [f for f in os.listdir(root_dir) if os.path.isdir(os.path.join(root_dir, f))]

    for folder_name in sorted(folders):
        folder_path = os.path.join(root_dir, folder_name)

        match = re.search(r'oil([\d\.]+)kPa', folder_name)
        if not match:
            continue
        O_val = float(match.group(1))

        print(f"\n[解析中] {folder_name} (数値 O = {O_val})")

        processor_dirs = glob.glob(os.path.join(folder_path, "processor*"))
        is_parallel = len(processor_dirs) > 0

        if is_parallel:
            p0_path = os.path.join(folder_path, "processor0")
            time_dirs = []
            for item in os.listdir(p0_path):
                if os.path.isdir(os.path.join(p0_path, item)):
                    try:
                        time_dirs.append((float(item), item))
                    except ValueError:
                        pass
            time_dirs.sort(key=lambda x: x[0])

            proc_paths = [p for p in sorted(processor_dirs) if os.path.isdir(p)]
            proc_meshes = {}
            for p_path in proc_paths:
                m_dir = os.path.join(p_path, "constant", "polyMesh")
                if not os.path.exists(m_dir) and not os.path.exists(m_dir + ".gz"):
                    m_dir = os.path.join(p_path, "0", "polyMesh")
                proc_meshes[p_path] = m_dir

            for t_float, t_str in tqdm(time_dirs, desc=f"Parallel ({len(proc_paths)} cores)"):
                all_coords, all_alphas = [], []
                for p_path in proc_paths:
                    t_dir = os.path.join(p_path, t_str)
                    alpha_file = os.path.join(t_dir, "alpha.water")

                    m_dir = proc_meshes[p_path]
                    centres = get_cell_centres_cached(m_dir, t_dir)
                    alphas = parse_foam_scalar(alpha_file)

                    if centres is not None and alphas is not None:
                        if isinstance(alphas, (float, int)):
                            alphas = np.full(len(centres), float(alphas))
                        if len(centres) == len(alphas):
                            all_coords.append(centres)
                            all_alphas.append(alphas)

                if len(all_coords) > 0:
                    coords_cat = np.vstack(all_coords)
                    alphas_cat = np.concatenate(all_alphas)
                    S_val, Nz, (dx, dy, dz) = calculate_S_value(coords_cat, alphas_cat)
                    records.append({"Folder": folder_name, "O": O_val, "Time": t_float, "S": S_val})
                    
                    if folder_name not in mesh_summaries:
                        mesh_summaries[folder_name] = {"O": O_val, "Nz": Nz, "dx": dx, "dy": dy, "dz": dz}

        else:
            time_dirs = []
            for item in os.listdir(folder_path):
                if os.path.isdir(os.path.join(folder_path, item)):
                    try:
                        time_dirs.append((float(item), item))
                    except ValueError:
                        pass
            time_dirs.sort(key=lambda x: x[0])

            m_dir = os.path.join(folder_path, "constant", "polyMesh")
            if not os.path.exists(m_dir) and not os.path.exists(m_dir + ".gz"):
                m_dir = os.path.join(folder_path, "0", "polyMesh")

            for t_float, t_str in tqdm(time_dirs, desc="Single Core"):
                t_dir = os.path.join(folder_path, t_str)
                alpha_file = os.path.join(t_dir, "alpha.water")

                centres = get_cell_centres_cached(m_dir, t_dir)
                alphas = parse_foam_scalar(alpha_file)

                if centres is not None and alphas is not None:
                    if isinstance(alphas, (float, int)):
                        alphas = np.full(len(centres), float(alphas))
                    if len(centres) == len(alphas):
                        S_val, Nz, (dx, dy, dz) = calculate_S_value(centres, alphas)
                        records.append({"Folder": folder_name, "O": O_val, "Time": t_float, "S": S_val})
                        
                        if folder_name not in mesh_summaries:
                            mesh_summaries[folder_name] = {"O": O_val, "Nz": Nz, "dx": dx, "dy": dy, "dz": dz}

    return pd.DataFrame(records), mesh_summaries


# ==============================================================================
# 5. 実行およびファイル出力 & ターミナル一覧表示
# ==============================================================================
if __name__ == "__main__":
    print("=== OpenFOAM シミュレーション解析プログラム (Docker環境) ===")
    print(f"解析対象: {SIM_RESULT_DIR}")

    df_result, mesh_summaries = process_simulation_folders(SIM_RESULT_DIR)

    if df_result.empty:
        print("\n[注意] 解析対象データが取得できませんでした。")
    else:
        print(f"\n解析完了: 合計 {len(df_result)} 件のレコードを取得しました。")

        # 1. ケース（フォルダ名）ごとのマトリックス形式出力
        df_pivot_folder = df_result.pivot_table(index=['O', 'Folder'], columns='Time', values='S', aggfunc='first')
        csv_folder_path = os.path.join(OUTPUT_DIR, "simulation_summary_by_folder.csv")
        df_pivot_folder.to_csv(csv_folder_path, encoding='utf-8-sig')
        print(f"[保存完了] ケース別マトリックス: {csv_folder_path}")

        # 2. Oの値ごとのマトリックス形式出力（重複するOの値は平均化）
        df_pivot_O = df_result.pivot_table(index='O', columns='Time', values='S', aggfunc='mean')
        csv_o_path = os.path.join(OUTPUT_DIR, "simulation_summary_by_O.csv")
        df_pivot_O.to_csv(csv_o_path, encoding='utf-8-sig')
        print(f"[保存完了] O値別マトリックス  : {csv_o_path}")

        # 3. 変換用メッシュパラメータ（Nz, セルサイズ等）のターミナル出力
        print("\n" + "="*80)
        print("■ 各ケースのメッシュパラメータ・変換値一覧 サマリー")
        print("="*80)
        df_mesh_info = pd.DataFrame.from_dict(mesh_summaries, orient='index')
        df_mesh_info.index.name = "Folder"
        
        # ターミナルへ綺麗に出力
        print(df_mesh_info.to_string())
        print("="*80 + "\n")