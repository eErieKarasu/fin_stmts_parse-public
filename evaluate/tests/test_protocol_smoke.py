"""Loopback protocol tests with local fixture files."""
import asyncio
import importlib.util
import socket
import sys
import logging
from types import SimpleNamespace
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from concurrent.futures import ThreadPoolExecutor

from evaluate.run import ROOT, GrpcClient, McpClient, add_project_imports, arguments


def case_fixture():
    return {
        "file": "files/input.pdf",
        "company": "测试公司",
        "fns_no": "FN191",
        "end_date": "202503",
        "report_type": "QTR",
    }

HAS_GRPC = importlib.util.find_spec('grpc') is not None
HAS_MCP = importlib.util.find_spec('mcp') is not None and importlib.util.find_spec('uvicorn') is not None


class ProtocolSmokeTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(HAS_GRPC, '需要项目 .venv 中的 grpcio')
    async def test_grpc_wire_request_and_response(self):
        add_project_imports()
        import grpc
        from protos import fin_stmts_parse_pb2 as pb, fin_stmts_parse_pb2_grpc as rpc
        # Exercise the production local-copy function without requiring the
        # parsing service's optional logging setup in the evaluation client env.
        spec = importlib.util.spec_from_file_location('evaluation_file_transfer_fixture',
            ROOT / 'apps/fin_stmts_parse/utils/file_transfer.py')
        transfer = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'fin_stmts_parse.utils.logger': SimpleNamespace(logger=logging.getLogger(__name__))}):
            spec.loader.exec_module(transfer)
        batch_download = transfer.batch_download
        temporary = tempfile.TemporaryDirectory()
        source = Path(temporary.name) / '本地 文件.pdf'
        source.write_bytes(b'local grpc fixture')
        destination = Path(temporary.name) / 'received'
        requests = []
        class Service(rpc.FinStmtsParseServicer):
            def parseFinStmts(self, request, context):
                requests.append(request)
                batch_download(request.finFiles, str(destination))
                return pb.ParseReply(dealSts='4', fnsItemBsBegin={'cash': '1.10'},
                                     fnsItemBsEnd={'cash': '2.20'}, fnsItemIs={'net': '-3.30'})
        server = grpc.server(ThreadPoolExecutor(max_workers=1))
        rpc.add_FinStmtsParseServicer_to_server(Service(), server)
        port = server.add_insecure_port('127.0.0.1:0')
        server.start()
        try:
            args = arguments(['grpc', '--host', '127.0.0.1', '--grpc-port', str(port)])
            with patch('requests.get', side_effect=AssertionError('local files must not be downloaded')):
                async with GrpcClient(args) as transport:
                    raw, pred = await transport.parse(case_fixture(), str(source), 1)
            self.assertEqual(requests[0].finFiles[0].fileUrl, str(source))
            self.assertEqual((destination / 'input.pdf').read_bytes(), source.read_bytes())
            self.assertEqual(requests[0].endDate, '202503')
            self.assertEqual(requests[0].fnsNo, 'FN191')
            self.assertEqual(raw['dealSts'], '4')
            self.assertEqual(pred[('profit', 'net', 'current')], '-3.30')
        finally:
            server.stop(0).wait()
            temporary.cleanup()

    @unittest.skipUnless(HAS_MCP, '需要项目 .venv 中的 MCP SDK 和 uvicorn')
    async def test_mcp_http_tool_chain(self):
        import uvicorn
        from mcp.server.fastmcp import FastMCP
        server = FastMCP('evaluation-fixture', stateless_http=True, json_response=True)
        temporary = tempfile.TemporaryDirectory()
        source = Path(temporary.name) / '本地 文件.pdf'
        source.write_bytes(b'local mcp fixture')
        calls = []
        @server.tool()
        def parse_fin_stmts_markdown(files: list[dict], session_id: str) -> list[dict]:
            calls.append(('parse', session_id, files))
            if Path(files[0]['path']).read_bytes() != b'local mcp fixture':
                raise ValueError('local fixture mismatch')
            return [{'file_name': 'input.pdf', 'markdown_files': []}]
        @server.tool()
        def fin_stmts_parse_map(parse_results: list[dict], session_id: str) -> list[dict]:
            calls.append(('map', session_id, parse_results))
            return [{'mapped_results': [{'table_type': 'profit', 'date': '202503', 'is_consolidated': False,
                                         'view_data': [{'code': 'net', 'values': ['100', '-3.30']}]}]}]
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        http = uvicorn.Server(uvicorn.Config(server.streamable_http_app(), log_level='error'))
        task = asyncio.create_task(http.serve(sockets=[sock]))
        try:
            for _ in range(100):
                if http.started: break
                if task.done(): await task
                await asyncio.sleep(.01)
            self.assertTrue(http.started, 'fixture server did not start')
            args = arguments(['mcp', '--url', f'http://127.0.0.1:{port}/mcp'])
            async with McpClient(args) as transport:
                raw, pred = await transport.parse(case_fixture(), str(source), 1)
            self.assertEqual(pred[('profit', 'net', 'current')], '-3.30')
            self.assertEqual([c[0] for c in calls], ['parse', 'map'])
            self.assertEqual(calls[0][1], calls[1][1])
            self.assertEqual(calls[1][2], raw['parse_results'])
        finally:
            http.should_exit = True
            await task
            sock.close()
            temporary.cleanup()


if __name__ == '__main__':
    unittest.main()
