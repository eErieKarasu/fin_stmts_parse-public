import argparse
import json
import os.path
import sys
import threading
import uuid
from datetime import datetime, timedelta

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .read_yaml import load_env_config


class S3Client:
    """
    S3 客户端，支持多配置切换（oss / llm_oss）
    
    使用方法：
        # 使用默认配置（oss）
        S3Client.upload_file(local_path, s3_path)
        
        # 使用 llm_oss 配置
        S3Client.upload_file(local_path, s3_path, config_key="llm_oss")
    """
    # 每个 config_key 维护独立的实例
    _instances = {}
    _instance_lock = threading.Lock()
    _connection_locks = {}
    def __new__(cls, config_key: str = "oss"):
        if config_key not in cls._instances:
            with cls._instance_lock:
                if config_key not in cls._instances:
                    instance = super(S3Client, cls).__new__(cls)
                    instance.s3_client = None
                    instance.bucket = None
                    instance.config_key = config_key
                    cls._instances[config_key] = instance
                    cls._connection_locks[config_key] = threading.Lock()
        return cls._instances[config_key]

    def _establish_connection(self):
        """执行实际的连接握手"""
        try:
            env = os.getenv("RUNNING_ENV", "local")
            env_config = load_env_config(env)
            
            # 根据 config_key 读取对应配置
            conf = env_config.get(self.config_key, {})
            if not conf:
                print(f"[S3 Error] 配置项 '{self.config_key}' 不存在")
                return False
                
            self.bucket = conf.get('bucket_name')

            # sdoss超时问题
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=conf.get('account_key_id'),
                aws_secret_access_key=conf.get('account_key_secret'),
                endpoint_url=conf.get('endpoint'),
                config=Config(
                    signature_version='s3v4',
                    retries={'max_attempts': 3, 'mode': 'standard'},
                    connect_timeout=5
                )
            )
            # 握手验证
            self.s3_client.head_bucket(Bucket=self.bucket)
            print(f"[S3 Success] 连接成功: config_key={self.config_key}, bucket={self.bucket}")
            return True
        except Exception as e:
            print(f"[S3 Error] Connection failed (config_key={self.config_key}): {e}")
            self.s3_client = None
            return False

    def _ensure_ready(self):
        """自愈逻辑：操作前检查连接，不可用则重连"""
        if self.s3_client:
            try:
                # 存活性检查 (Heartbeat)
                self.s3_client.head_bucket(Bucket=self.bucket)
                return True
            except (ClientError, BotoCoreError):
                self.s3_client = None
                pass

        connection_lock = self._connection_locks.get(self.config_key)
        if connection_lock:
            with connection_lock:
                if self.s3_client:  # 二次检查防止竞争
                    return True
                return self._establish_connection()
        return self._establish_connection()

    @staticmethod
    def upload_file(local_file_path, s3_file_path, days=10, config_key: str = "oss", expires=3600):
        """
        上传本地文件，并返回带签名的临时访问链接。
        
        Args:
            local_file_path: 本地文件路径
            s3_file_path: S3 文件路径
            days: 文件过期天数
            config_key: 配置键，"oss" 或 "llm_oss"
            expires: 临时访问链接过期时间（秒）

        Returns:
            str | None: 上传成功时返回 presigned URL，失败返回 None
        """
        ins = S3Client(config_key)
        if ins._ensure_ready():
            try:
                expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
                ins.s3_client.upload_file(local_file_path, ins.bucket, s3_file_path,ExtraArgs={"Tagging": f"ExpiryDate = {expiry_date}&ExpiryDays={days}"})
                print(f"[S3 Success] 文件上传成功: {s3_file_path} (config_key={config_key})")
                return ins.s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': ins.bucket, 'Key': s3_file_path},
                    ExpiresIn=expires,
                )
            except ClientError as e:
                print(f"Upload Error: {e}")
        return None

    @staticmethod
    def download_file(s3_file_path, local_path, config_key: str = "oss"):
        """
        通用下载 (自动创建本地目录)
        
        Args:
            s3_file_path: S3 文件路径
            local_path: 本地保存路径
            config_key: 配置键，"oss" 或 "llm_oss"
        """
        ins = S3Client(config_key)
        if ins._ensure_ready():
            try:
                os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
                ins.s3_client.download_file(ins.bucket, s3_file_path, local_path)
                return True
            except ClientError as e:
                print(f"Download Error: {e}")
        return False

    @staticmethod
    def list_files(prefix='', limit=100, token=None, config_key: str = "oss"):
        """
        分页获取列表 (通用分页逻辑)
        
        Args:
            prefix: 文件前缀
            limit: 最大返回数量
            token: 分页 token
            config_key: 配置键，"oss" 或 "llm_oss"
        """
        ins = S3Client(config_key)
        if not ins._ensure_ready():
            return [], None
        try:
            params = {'Bucket': ins.bucket, 'Prefix': prefix, 'MaxKeys': limit}
            if token: params['ContinuationToken'] = token
            resp = ins.s3_client.list_objects_v2(**params)
            files = [obj['Key'] for obj in resp.get('Contents', [])]
            return files, resp.get('NextContinuationToken')
        except ClientError:
            return [], None

    @staticmethod
    def create_presigned_url(oss_object_path, expires=3600, config_key: str = "oss"):
        """
        获取带签名的临时访问链接
        
        Args:
            oss_object_path: S3 对象路径
            expires: 过期时间（秒）
            config_key: 配置键，"oss" 或 "llm_oss"
        """
        ins = S3Client(config_key)
        if not ins._ensure_ready(): return None
        return ins.s3_client.generate_presigned_url(
            'get_object', Params={'Bucket': ins.bucket, 'Key': oss_object_path}, ExpiresIn=expires
        )

    @staticmethod
    def delete_file(object_key, config_key: str = "oss"):
        """
        从 S3 路径删除文件
        
        Args:
            object_key: S3 上的文件完整路径 (Key)
            config_key: 配置键，"oss" 或 "llm_oss"
        Returns:
            bool 是否删除成功
        """
        ins = S3Client(config_key)
        # 1. 确保连接可用（如果断开会自动重连）
        if not ins._ensure_ready(): return False
        try:
            ins.s3_client.delete_object(Bucket=ins.bucket, Key=object_key)
            print(f"[S3 Success] 文件已删除: {object_key}")
            return True
        except ClientError as e:
            print(f"[S3 Error] 删除执行异常: {e}")
            return False

    @staticmethod
    def delete_files(object_keys: list, config_key: str = "oss"):
        """
        批量删除文件 (单次最高支持 1000 个)
        
        Args:
            object_keys: 包含多个 Key 的列表
            config_key: 配置键，"oss" 或 "llm_oss"
        """
        if not object_keys:
            return True
        ins = S3Client(config_key)
        if not ins._ensure_ready():return False
        try:
            # 构建批量删除的数据结构
            delete_objects = {'Objects': [{'Key': k} for k in object_keys]}
            ins.s3_client.delete_objects(Bucket=ins.bucket, Delete=delete_objects)
            print(f"[S3 Success] 成功批量删除 {len(object_keys)} 个文件")
            return True
        except ClientError as e:
            print(f"[S3 Error] 批量删除异常: {e}")
            return False


def _build_parser():
    parser = argparse.ArgumentParser(description="S3Client helper")
    subparsers = parser.add_subparsers(dest="command")

    upload_parser = subparsers.add_parser("upload", help="Upload a local file")
    upload_parser.add_argument("local_file_path")
    upload_parser.add_argument("--prefix", required=True, help="S3 prefix, e.g. llm/report_gen/")
    upload_parser.add_argument("--days", type=int, default=10)
    upload_parser.add_argument("--config-key", default="oss")

    download_parser = subparsers.add_parser("download", help="Download an S3 object")
    download_parser.add_argument("s3_file_path")
    download_parser.add_argument("local_path")
    download_parser.add_argument("--config-key", default="oss")

    presign_parser = subparsers.add_parser("presign", help="Create a presigned URL")
    presign_parser.add_argument("s3_file_path")
    presign_parser.add_argument("--expires", type=int, default=3600)
    presign_parser.add_argument("--config-key", default="oss")

    list_parser = subparsers.add_parser("list", help="List objects under a prefix")
    list_parser.add_argument("--prefix", default="")
    list_parser.add_argument("--limit", type=int, default=100)
    list_parser.add_argument("--token")
    list_parser.add_argument("--config-key", default="oss")

    delete_parser = subparsers.add_parser("delete", help="Delete an S3 object")
    delete_parser.add_argument("s3_file_path")
    delete_parser.add_argument("--config-key", default="oss")

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "upload":
        normalized_prefix = args.prefix.strip().strip("/")
        s3_file_path = f"{normalized_prefix}/{uuid.uuid4()}" if normalized_prefix else str(uuid.uuid4())
        file_url = S3Client.upload_file(
            args.local_file_path,
            s3_file_path,
            days=args.days,
            config_key=args.config_key,
        )
        if file_url:
            print(json.dumps({"s3_file_path": s3_file_path, "fileUrl": file_url}, ensure_ascii=False))
        sys.exit(0 if file_url else 1)

    if args.command == "download":
        success = S3Client.download_file(
            args.s3_file_path,
            args.local_path,
            config_key=args.config_key,
        )
        sys.exit(0 if success else 1)

    if args.command == "presign":
        url = S3Client.create_presigned_url(
            args.s3_file_path,
            expires=args.expires,
            config_key=args.config_key,
        )
        if not url:
            sys.exit(1)
        print(url)
        return

    if args.command == "list":
        files, token = S3Client.list_files(
            prefix=args.prefix,
            limit=args.limit,
            token=args.token,
            config_key=args.config_key,
        )
        print(json.dumps({"files": files, "next_token": token}, ensure_ascii=False, indent=2))
        return

    if args.command == "delete":
        success = S3Client.delete_file(args.s3_file_path, config_key=args.config_key)
        sys.exit(0 if success else 1)

    parser.print_help()


if __name__ == '__main__':
    main()




