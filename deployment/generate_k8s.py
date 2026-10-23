import os
from string import Template

# ================= 配置区域 =================
# 在这里定义你要替换的变量值
# 你也可以修改代码从 环境变量(os.environ) 读取
CONFIG = {
    "APP_ID": "demo-app",
    "NAMESPACE": os.getenv("NAMESPACE", "default"),
    "IMAGE": os.getenv("IMAGE", "fin-stmts-parse:latest"),
    "GRPC_APP_PATH": "apps/fin_stmts_parse_grpc",
    "MCP_APP_PATH": "apps/fin_stmts_parse_mcp",
}

# ===========================================

def generate_yaml():
    # 获取当前脚本所在的目录
    current_dir = os.path.dirname(os.path.abspath(__file__))

    print(f"--- 开始生成 YAML 文件 (当前目录: {current_dir}) ---")
    template_path = os.path.join(current_dir, "template.yaml")
    output_path = os.path.join(current_dir, f"{CONFIG['APP_ID']}.yaml")

    try:
        # 1. 读取模板文件 (指定 utf-8 防止中文乱码)
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 2. 创建模板对象
        src = Template(content)

        # 3. 执行替换
        # safe_substitute: 如果模板里有变量没在 CONFIG 里定义，不会报错，而是保留原样
        # substitute: 如果有变量没定义，会直接报错 (建议调试时用这个)
        result = src.substitute(CONFIG)

        # 4. 写入新文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result)


    except KeyError as e:
        print(f"[错误] 模板文件中存在未定义的变量: {e}")
    except Exception as e:
        print(f"[失败] 处理模板时发生错误: {e}")

    print("--- 生成结束 ---")


if __name__ == "__main__":
    generate_yaml()
