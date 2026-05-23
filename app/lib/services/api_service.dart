import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/agent.dart';

class ApiService {
  String? _baseUrl;
  String? _token;

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    final defaultUrl = kIsWeb ? 'http://localhost:8000' : 'http://localhost:8000';
    _baseUrl = prefs.getString('server_url') ?? defaultUrl;
    _token = prefs.getString('token');
  }

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (_token != null) 'Authorization': 'Bearer $_token',
  };

  void setBaseUrl(String url) => _baseUrl = url;
  String? get token => _token;

  // Auth
  Future<User> register(String username, String password) async {
    final r = await http.post(
      Uri.parse('$_baseUrl/api/auth/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username, 'password': password}),
    );
    final data = jsonDecode(r.body);
    if (r.statusCode == 200) {
      await _saveToken(data['token']);
      return User.fromJson(data['user']);
    }
    throw Exception(data['detail'] ?? 'Register failed');
  }

  Future<User> login(String username, String password) async {
    final r = await http.post(
      Uri.parse('$_baseUrl/api/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username, 'password': password}),
    );
    final data = jsonDecode(r.body);
    if (r.statusCode == 200) {
      await _saveToken(data['token']);
      return User.fromJson(data['user']);
    }
    throw Exception(data['detail'] ?? 'Login failed');
  }

  Future<void> _saveToken(String token) async {
    _token = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('token', token);
  }

  // VoiceAgents
  Future<List<VoiceAgent>> listAgents() async {
    final r = await http.get(Uri.parse('$_baseUrl/api/agents'), headers: _headers);
    if (r.statusCode == 200) {
      final list = jsonDecode(r.body) as List;
      return list.map((e) => VoiceAgent.fromJson(e)).toList();
    }
    throw Exception('Failed to list agents');
  }

  Future<VoiceAgent> createAgent(String alias, String systemPrompt, String filePath) async {
    final uri = Uri.parse('$_baseUrl/api/agents');
    final request = http.MultipartRequest('POST', uri)
      ..headers['Authorization'] = 'Bearer $_token'
      ..fields['alias'] = alias
      ..fields['system_prompt'] = systemPrompt
      ..files.add(await http.MultipartFile.fromPath('audio_file', filePath));
    final streamed = await request.send();
    final r = await http.Response.fromStream(streamed);
    if (r.statusCode == 200) {
      return VoiceAgent.fromJson(jsonDecode(r.body));
    }
    throw Exception('Failed to create agent');
  }

  Future<void> deleteAgent(String id) async {
    final r = await http.delete(Uri.parse('$_baseUrl/api/agents/$id'), headers: _headers);
    if (r.statusCode != 204) throw Exception('Failed to delete agent');
  }

  Future<VoiceAgent> updateAgent(String id, String alias, String systemPrompt) async {
    final r = await http.patch(
      Uri.parse('$_baseUrl/api/agents/$id'),
      headers: _headers,
      body: jsonEncode({'alias': alias, 'system_prompt': systemPrompt}),
    );
    if (r.statusCode == 200) {
      return VoiceAgent.fromJson(jsonDecode(r.body));
    }
    throw Exception('Failed to update agent');
  }

  // Call
  Future<Map<String, String>> getCallToken(String agentId) async {
    final r = await http.post(
      Uri.parse('$_baseUrl/api/call/token'),
      headers: _headers,
      body: jsonEncode({'agent_id': agentId}),
    );
    if (r.statusCode == 200) {
      final data = jsonDecode(r.body);
      return {'token': data['token'], 'room_url': data['room_url']};
    }
    throw Exception('Failed to get call token');
  }

  // Admin
  Future<List<Map<String, dynamic>>> listAllVoiceAgents() async {
    final r = await http.get(Uri.parse('$_baseUrl/api/admin/agents'), headers: _headers);
    if (r.statusCode == 200) {
      return (jsonDecode(r.body) as List).cast<Map<String, dynamic>>();
    }
    throw Exception('Failed to list all agents');
  }

  Future<void> grantPermission(String agentId, String username) async {
    final r = await http.post(
      Uri.parse('$_baseUrl/api/agents/$agentId/grant'),
      headers: _headers,
      body: jsonEncode({'username': username}),
    );
    if (r.statusCode != 200) throw Exception('Failed to grant permission');
  }

  Future<void> revokePermission(String agentId, String username) async {
    final r = await http.delete(
      Uri.parse('$_baseUrl/api/agents/$agentId/grant/$username'),
      headers: _headers,
    );
    if (r.statusCode != 204) throw Exception('Failed to revoke permission');
  }

  // Settings
  Future<void> logout() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('token');
  }
}
