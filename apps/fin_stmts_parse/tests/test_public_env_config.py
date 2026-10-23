import os
import unittest
from unittest.mock import patch

from fin_stmts_parse.utils.read_yaml import _expand_env, load_env_config


class PublicEnvConfigTests(unittest.TestCase):
    def test_recursive_environment_expansion_preserves_other_values(self):
        with patch.dict(os.environ, {"VLM_API_KEY": "synthetic-test-only"}, clear=True):
            self.assertEqual(
                _expand_env({"key": "${VLM_API_KEY:-}", "nested": ["${MISSING:-fallback}", 3, False]}),
                {"key": "synthetic-test-only", "nested": ["fallback", 3, False]},
            )

    def test_all_environments_have_no_embedded_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            for env in ("local", "dev", "sit", "uat", "prod"):
                config = load_env_config(env)
                for section in ("vlm", "llm", "oss", "llm_oss", "agent_oss", "postgres"):
                    for key in ("api_key", "account_key_id", "account_key_secret", "dsn"):
                        if key in config.get(section, {}):
                            self.assertEqual(config[section][key], "", (env, section, key))
