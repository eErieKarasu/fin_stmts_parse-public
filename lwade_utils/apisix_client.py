# apisix_client.py
from lwade_config import config
import logging
import requests

logger = logging.getLogger(__name__)


class APISIXClient:
    def __init__(self, admin_url: str, admin_key: str):
        self.admin_url = admin_url.rstrip("/")
        self.headers = {
            "X-API-KEY": admin_key,
            "Content-Type": "application/json"
        }

    def upsert_upstream(self, upstream_name:str, nodes: dict):
        """创建或更新上游节点"""
        url = f"{self.admin_url}/apisix/admin/upstreams/{upstream_name}"

        payload = {
            "nodes": nodes,
            "key": "remote_addr",
            "type": "chash"
        }

        # 先尝试 PUT（更新）
        resp = requests.put(url, headers=self.headers, json=payload, timeout=10)
        if resp.status_code in (200, 201):
            logger.info(f"Upstream '{upstream_name}' updated")
            return

        # 如果不存在，POST 创建
        if resp.status_code == 404:
            resp = requests.post(
                f"{self.admin_url}/apisix/admin/upstreams",
                headers=self.headers,
                json={"name": upstream_name, "nodes": nodes, "type": type},
                timeout=10
            )
            if resp.status_code == 201:
                logger.info(f"Upstream '{upstream_name}' created")
                return

        raise Exception(f"Failed to upsert upstream: {resp.status_code} {resp.text}")

    def upsert_proto(self, content: str) -> int:
        """上传或更新 proto，返回 proto_id"""
        url = f"{self.admin_url}/apisix/admin/protos/proto-{config.APPID}"
        payload = {"content": content}

        # 先尝试 PUT（更新）
        resp = requests.put(url, headers=self.headers, json=payload, timeout=10)
        if resp.status_code in (200, 201):
            data = resp.json()
            proto_id = data['value']["id"]
            print(f"Proto 'proto-{config.APPID}' updated")
            return proto_id

        # 如果不存在，POST 创建
        if resp.status_code == 404:
            resp = requests.post(
                f"{self.admin_url}/apisix/admin/protos",
                headers=self.headers,
                json={"name": f"proto-{config.APPID}", "content": content},
                timeout=10
            )
            if resp.status_code == 201:
                data = resp.json()
                proto_id = data["data"]["id"]
                print(f"Proto 'proto-{config.APPID}' created, id={proto_id}")
                return proto_id

        raise Exception(f"Failed to upsert proto: {resp.status_code} {resp.text}")

    def upsert_route(self):
        """创建或更新路由"""
        url = f"{self.admin_url}/apisix/admin/routes/route-{config.APPID}"

        payload = {
            "uri": f"/{config.APPID}/*",
            "name": config.APPID,
            "methods": ["POST", "GET", "PUT"],
            "upstream": {
                "hash_on": "vars",
                "scheme": "grpc",
                "pass_host": "pass",
                "type": "roundrobin",
                "nodes": [
                    {
                        "host": f"{config.APPID}-hl",
                        "weight": 100,
                        "priority": 0,
                        "port": 50051
                    }
                ],
                "tls": {
                    "verify": False
                }
            },
            "plugin_config_id": config.PLUGIN_CONFIG
        }

        resp = requests.put(url, headers=self.headers, json=payload, timeout=10)
        if resp.status_code in (200, 201):
            print(f"Route 'route-{config.APPID}' registered")
        else:
            raise Exception(f"Failed to register route: {resp.status_code} {resp.text}")


apisix_client = APISIXClient(config.APISIX_ADMIN_URL, config.APISIX_ADMIN_KEY)