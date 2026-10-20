import 'package:call_me/models/agent.dart';
import 'package:call_me/services/api_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
      'Agent response uses voice pool and runtime mode without provider voice id',
      () {
    final agent = VoiceAgent.fromJson({
      'id': 'agent-1',
      'alias': '实时助手',
      'voice_pool_id': 'voice-pool-1',
      'system_prompt': '你好',
      'owner_id': 'user-1',
      'runtime_mode': 'realtime',
      'provider': 'qwen',
      'created_at': '2026-10-20T00:00:00Z',
    });

    expect(agent.voicePoolId, 'voice-pool-1');
    expect(agent.runtimeMode, 'realtime');
    expect(agent.provider, 'qwen');
  });

  test('Realtime token rejection has a safe user-facing message', () {
    final error = CallTokenException.fromResponse(
      400,
      '{"detail":"Realtime agent configuration is incomplete"}',
    );

    expect(error.userMessage, '该 Agent 的实时语音服务暂不可用');
    expect(error.userMessage, isNot(contains('configuration')));
  });

  test('Pipeline token rejection keeps the generic connection message', () {
    final error = CallTokenException.fromResponse(
      503,
      '{"detail":"upstream unavailable"}',
    );

    expect(error.userMessage, '连接失败，请稍后重试');
  });

  test('Malformed token error details stay generic', () {
    final error = CallTokenException.fromResponse(
      500,
      '{"detail":{"provider_voice_id":"must-not-display"}}',
    );

    expect(error.userMessage, '连接失败，请稍后重试');
  });
}
