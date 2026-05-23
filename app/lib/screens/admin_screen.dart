import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';

class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  List<Map<String, dynamic>> _agents = [];
  List<Map<String, dynamic>> _users = [];
  Map<String, List<Map<String, dynamic>>> _userAgents = {};
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final api = context.read<ApiService>();
    try {
      final results = await Future.wait([api.listAllAgents(), api.listUsers()]);
      _agents = results[0] as List<Map<String, dynamic>>;
      _users = results[1] as List<Map<String, dynamic>>;
    } catch (_) {}
    setState(() => _loading = false);
  }

  Future<void> _loadUserAgents(String username) async {
    try {
      final agents = await context.read<ApiService>().listUserAgents(username);
      setState(() => _userAgents[username] = agents);
    } catch (_) {}
  }

  Future<void> _grant(String agentId) async {
    final username = await showDialog<String>(
      context: context,
      builder: (ctx) {
        final ctrl = TextEditingController();
        return AlertDialog(
          title: const Text('Grant Agent to User'),
          content: TextField(controller: ctrl, decoration: const InputDecoration(hintText: 'Username')),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
            TextButton(onPressed: () => Navigator.pop(ctx, ctrl.text.trim()), child: const Text('Grant')),
          ],
        );
      },
    );
    if (username != null && username.isNotEmpty) {
      try {
        await context.read<ApiService>().grantPermission(agentId, username);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Agent copy granted to $username')));
          _load();
        }
      } catch (e) {
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed: $e')));
      }
    }
  }

  Future<void> _deleteAgent(String agentId, String alias) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete Agent'),
        content: Text('Delete "$alias"? This only affects this user\'s copy.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Delete')),
        ],
      ),
    );
    if (confirm == true) {
      try {
        await context.read<ApiService>().deleteAgent(agentId);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Deleted')));
          _load();
        }
      } catch (e) {
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));

    // Build a map: owner_id -> list of agents
    final userAgentMap = <String, List<Map<String, dynamic>>>{};
    for (final a in _agents) {
      final ownerId = a['owner_id'] as String;
      userAgentMap.putIfAbsent(ownerId, () => []).add(a);
    }
    // Map owner_id to username
    final idToUsername = <String, String>{};
    for (final u in _users) {
      idToUsername[u['id'] as String] = u['username'] as String;
    }

    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Admin Panel'),
          bottom: const TabBar(tabs: [
            Tab(text: 'By User'),
            Tab(text: 'All Agents'),
            Tab(text: 'Users'),
          ]),
        ),
        body: TabBarView(children: [
          _buildByUserTab(userAgentMap, idToUsername),
          _buildAllAgentsTab(),
          _buildUsersTab(userAgentMap, idToUsername),
        ]),
      ),
    );
  }

  Widget _buildByUserTab(Map<String, List<Map<String, dynamic>>> userAgentMap, Map<String, String> idToUsername) {
    final entries = userAgentMap.entries.toList();
    if (entries.isEmpty) return const Center(child: Text('No agents'));

    return ListView.builder(
      itemCount: entries.length,
      itemBuilder: (_, i) {
        final e = entries[i];
        final username = idToUsername[e.key] ?? e.key.substring(0, 8);
        return ExpansionTile(
          leading: const Icon(Icons.person),
          title: Text('$username (${e.value.length} agents)'),
          children: e.value.map((a) => ListTile(
            title: Text(a['alias'] ?? ''),
            subtitle: Text('Prompt: ${(a['system_prompt'] ?? '').toString().substring(0, 50)}...'),
            trailing: IconButton(
              icon: const Icon(Icons.delete_outline, size: 20),
              onPressed: () => _deleteAgent(a['id'], a['alias'] ?? ''),
            ),
          )).toList(),
        );
      },
    );
  }

  Widget _buildAllAgentsTab() {
    return ListView.builder(
      itemCount: _agents.length,
      itemBuilder: (_, i) {
        final a = _agents[i];
        return ListTile(
          title: Text(a['alias'] ?? ''),
          subtitle: Text('Voice: ${(a['voice_id'] ?? '').toString().substring(0, 25)}...'),
          trailing: IconButton(
            icon: const Icon(Icons.person_add),
            onPressed: () => _grant(a['id']),
          ),
        );
      },
    );
  }

  Widget _buildUsersTab(Map<String, List<Map<String, dynamic>>> userAgentMap, Map<String, String> idToUsername) {
    return ListView.builder(
      itemCount: _users.length,
      itemBuilder: (_, i) {
        final u = _users[i];
        final uid = u['id'] as String;
        final agentCount = userAgentMap[uid]?.length ?? 0;
        return ListTile(
          leading: Icon(u['role'] == 'admin' ? Icons.shield : Icons.person),
          title: Text(u['username'] ?? ''),
          subtitle: Text('Role: ${u['role']} | Agents: $agentCount'),
        );
      },
    );
  }
}
