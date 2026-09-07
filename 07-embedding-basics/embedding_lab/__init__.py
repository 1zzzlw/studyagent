"""07-embedding-basics 的教学代码包。

包被导入时先加载 studyAgent 根目录的 .env。这样后续再导入 OpenAI SDK 时，
看到的是同一份环境配置；密钥仍只存在于环境变量中。
"""

from pathlib import Path

from dotenv import load_dotenv


MODULE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = MODULE_ROOT.parent

load_dotenv(PROJECT_ROOT / ".env", override=False)


