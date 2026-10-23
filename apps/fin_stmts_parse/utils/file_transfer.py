import os
import requests
from typing import List, Dict
import shutil
from fin_stmts_parse.utils.logger import logger
from fin_stmts_parse.exceptions.base_exception import ServiceError

def ensure_clean_dir(dir_path: str) -> None:
    """
    如果指定目录存在，则删除整个目录（包括所有子目录和文件）；
    """
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)
        logger.info(f"已删除目录: {dir_path}")


# ======================
# 批量下载接口
# ======================
def batch_download(
    files: List[Dict[str, str]],
    local_dir: str,
    clean_dir: bool = True,
    overwrite: bool = True
) -> None:
    """
    批量下载文件到本地目录（支持HTTP/HTTPS URL和本地文件路径）。
    
    参数:
        files (List[Dict]): 每个元素为 {"fileName": "xxx", "fileUrl": "URL或本地路径"}
        local_dir (str): 本地保存目录
        clean_dir (bool): 是否在下载前删除整个 local_dir 并重建（默认 True）
        overwrite (bool): 是否覆盖已存在的文件（默认 True）

    行为说明:
        - 若 clean_dir=True，则无视 overwrite，直接清空整个目录。
        - 若 clean_dir=False，则根据 overwrite 决定是否跳过已有文件。
        - 若 fileUrl 以 http:// 或 https:// 开头，则从URL下载。
        - 若 fileUrl 是本地路径，则直接复制文件。
    """
    # 步骤 1: 处理目录清理
    if clean_dir:
        ensure_clean_dir(local_dir)

    # 步骤 2: 确保目录存在
    os.makedirs(local_dir, exist_ok=True)

    # 步骤 3: 逐个下载
    for item in files:
        filename = item.fileName
        source = item.fileUrl

        if not filename or not source:
            logger.info(f"⚠️ 跳过无效项: {item}")
            continue
        local_path = os.path.join(local_dir, filename)
        # 如果不覆盖且文件已存在，跳过
        if not overwrite and os.path.exists(local_path):
            logger.info(f"⏭️  跳过（已存在且不覆盖）: {filename}")
            continue
        
        # 判断是HTTP/HTTPS URL还是本地文件路径
        if source.startswith(('http://', 'https://')):
            # 从URL下载
            logger.info(f"📥 下载: {source} -> {local_path}")
            try:
                with requests.get(source, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    with open(local_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                logger.info(f"✅ 成功: {filename}")
            except Exception as e:
                raise ServiceError("3", f"文件下载失败：{filename}", str(e))
                # logger.info(f"❌ 失败: {filename} | 错误: {e}")
        else:
            # 从本地路径复制
            logger.info(f"📋 复制: {source} -> {local_path}")
            try:
                if not os.path.exists(source):
                    raise FileNotFoundError(f"源文件不存在: {source}")
                shutil.copy2(source, local_path)
                logger.info(f"✅ 成功: {filename}")
            except Exception as e:
                raise ServiceError("3", f"文件下载失败：{filename}", str(e))
                #logger.info(f"❌ 失败: {filename} | 错误: {e}")


# ======================
# 未来：上传接口（预留）
# ======================
def batch_upload(
        files: List[Dict[str, str]],
        destination_prefix: str,  # 如 "oss://my-bucket/uploads/"
        auth=None
) -> None:
    """
    未来可实现上传到 OSS/S3 等。
    files 示例: [{"local_path": "./a.pdf", "remote_name": "a.pdf"}]
    """
    raise NotImplementedError("Upload feature coming soon!")



def get_all_files(root_path: str) -> list[str]:
    """
    使用 os.walk 获取所有文件的绝对路径列表。
    """
    if not os.path.exists(root_path):
        raise FileNotFoundError(f"路径不存在: {root_path}")
    file_list = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        for filename in filenames:
            file_list.append(os.path.join(dirpath, filename))
    return file_list


