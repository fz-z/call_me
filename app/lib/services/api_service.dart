import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/agent.dart';

class ApiService {
  String? _baseUrl;
  String? _token;
  User? _currentUser;

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    // Auto-detect API URL from current page origin on web
    final defaultUrl = kIsWeb ? Uri.base.origin : 'http://localhost:8000';
    _baseUrl = prefs.getString('server_url') ?? defaultUrl;
    _token = prefs.getString('token');
    final role = prefs.getString('user_role');
    final username = prefs.getString('user_username');
    final userId = prefs.getString('user_id');
    final createdAt = prefs.getString('user_created_at') ?? '';
    if (role != null && username != null && userId != null) {
      _currentUser = User(id: userId, username: username, role: role, createdAt: createdAt);
    }
  }

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (_token != null) 'Authorization': 'Bearer $_token',
  };

  void setBaseUrl(String url) => _baseUrl = url;
  String? get token => _token;
  User? get currentUser => _currentUser;
  bool get isAdmin => _currentUser?.role == 'admin';

  Future<void> _saveUser(User user) async {
    _currentUser = user;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('user_role', user.role);
    await prefs.setString('user_username', user.username);
    await prefs.setString('user_id', user.id);
    await prefs.setString('user_created_at', user.createdAt);
  }

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
      final user = User.fromJson(data['user']);
      await _saveUser(user);
      return user;
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
      final user = User.fromJson(data['user']);
      await _saveUser(user);
      return user;
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

  // Settings
  Future<void> logout() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('token');
  }
}
