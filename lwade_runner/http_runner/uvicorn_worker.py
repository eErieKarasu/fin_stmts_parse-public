import logging.config
import os

from uvicorn_worker import UvicornWorker

from lwade_utils.log_utils import get_uvicorn_log_config

class CustomUvicornWorker(UvicornWorker):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        server_type = os.environ.get("SERVER_TYPE")
        log_config_dict = get_uvicorn_log_config(server=server_type)
        self.config.log_config = log_config_dict
        logging.config.dictConfig(log_config_dict)