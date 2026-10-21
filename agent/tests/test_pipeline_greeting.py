import ast
import unittest
from pathlib import Path


class PipelineGreetingTests(unittest.TestCase):
    def test_fallback_greeting_uses_agent_interruption_setting(self):
        source = Path(__file__).resolve().parents[1].joinpath("agent.py").read_text()
        module = ast.parse(source)
        pipeline = next(
            node for node in module.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_pipeline_call"
        )
        greeting = next(
            node for node in ast.walk(pipeline)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_speak_greeting"
        )
        fallback = next(
            node for node in ast.walk(greeting)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "say"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "你好，请问有什么可以帮助你的？"
        )
        interruption = next(keyword.value for keyword in fallback.keywords if keyword.arg == "allow_interruptions")

        self.assertIsInstance(interruption, ast.Name)
        self.assertEqual(interruption.id, "allow_interruptions")
