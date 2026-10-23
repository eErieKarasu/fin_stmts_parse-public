from enum import Enum
from typing import List, Union, Set


class RunnerType(Enum):
    GRPC = "grpc"
    SSE = "sse"
    A2A = "a2a"
    MCP = "mcp"

    @classmethod
    def get_all_values(cls) -> List[str]:
        return [member.value for member in cls]

    @classmethod
    def get_http_worker_values(cls) -> List[str]:
        return ["sse", "a2a", "mcp"]

    @classmethod
    def get_all_members(cls) -> List["RunnerType"]:
        """返回所有枚举成员实例列表（按定义顺序）"""
        return list(cls)

    @classmethod
    def from_string(cls, value: str) -> "RunnerType":
        val = value.strip().lower()
        for member in cls:
            if member.value == val:
                return member
        raise ValueError(f"Invalid runner type: '{value}'. Valid: {cls.get_all_values()}")


class AppRunner:
    @staticmethod
    def parse(value: Union[str, List[str], None]) -> List[RunnerType]:
        """
        解析输入，返回 RunnerType 枚举列表。

        输入支持:
            - "grpc"          -> [RunnerType.GRPC]
            - "grpc,a2a"      -> [RunnerType.A2A, RunnerType.GRPC] (自动排序)
            - ["grpc", "sse"] -> [RunnerType.GRPC, RunnerType.SSE]
            - "all" / None    -> 所有枚举成员

        返回:
            排序后的 RunnerType 列表。
        """
        # 1. 处理 "all" 或 None
        if value is None or (isinstance(value, str) and value.strip().lower() == "all"):
            return sorted(RunnerType, key=lambda x: x.value)
        # 2. 统一转换为字符串列表
        if isinstance(value, str):
            if "all" in [x.strip().lower() for x in value.split(",")]:
                return sorted(RunnerType, key=lambda x: x.value)
            items = [x.strip() for x in value.split(",")]
        elif isinstance(value, list):
            # 检查列表中是否包含 "all"
            if any(str(x).strip().lower() == "all" for x in value):
                return sorted(RunnerType, key=lambda x: x.value)
            items = [str(x).strip() for x in value]
        else:
            raise TypeError(f"Unsupported type: {type(value)}")
        # 3. 过滤空值并转换
        cleaned_items = [x for x in items if x]
        if not cleaned_items:
            return sorted(RunnerType, key=lambda x: x.value)
        # 4. 转换为枚举并去重
        result_set: Set[RunnerType] = set()
        for item in cleaned_items:
            result_set.add(RunnerType.from_string(item))
        # 5. 排序返回 (按枚举的值排序)
        return sorted(result_set, key=lambda x: x.value)


if __name__ == "__main__":
    # 案例 1: 单个字符串
    runners = AppRunner.parse("grpc")
    print(runners)
    # 输出: [<RunnerType.GRPC: 'grpc'>]

    # 案例 2: 多个字符串 (自动排序)
    runners = AppRunner.parse("grpc,a2a")
    print(runners)
    # 输出: [<RunnerType.A2A: 'a2a'>, <RunnerType.GRPC: 'grpc'>]
    # 案例 3: 获取具体的值用于业务逻辑
    for runner in AppRunner.parse("sse,mcp"):
        print(f"启动服务: {runner.value}")
        # 输出:
        # 启动服务: mcp
        # 启动服务: sse
    # 案例 4: 类型判断 (非常安全)
    target = AppRunner.parse("grpc")[0]
    if target is RunnerType.GRPC:
        print("这是 GRPC 服务")
    # 案例 5: "all"
    all_runners = AppRunner.parse("all")
    print(all_runners)
    print(f"所有服务: {[r.value for r in all_runners]}")
    # 输出: ['a2a', 'grpc', 'mcp', 'sse']

    print(RunnerType.A2A in all_runners)
    # 输出: True
