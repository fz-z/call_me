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

  Future<void> _grant(String agentId) async {
    final username = await showDialog<String>(
      context: context,
      builder: (ctx) {
        final ctrl = TextEditingController();
        return AlertDialog(
          title: const Text('Grant Access'),
          content: TextField(controller: ctrl, decoration: const InputDecoration(hintText: 'Username')),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
            TextButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('Grant'),
            ),
          ],
        );
      },
    );
    if (username != null && username.isNotEmpty) {
      try {
        await context.read<ApiService>().grantPermission(agentId, username);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Granted to $username')));
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed: $e')));
        }
      }
    }
  }

  Future<void> _revoke(String agentId, String username) async {
    try {
      await context.read<ApiService>().revokePermission(agentId, username);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Revoked from $username')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Admin Panel'),
          bottom: const TabBar(tabs: [
            Tab(text: 'All Agents'),
            Tab(text: 'Users'),
          ]),
        ),
        body: TabBarView(children: [
          _buildAgentsTab(),
          _buildUsersTab(),
        ]),
      ),
    );
  }

  Widget _buildAgentsTab() {
    return ListView.builder(
      itemCount: _agents.length,
      itemBuilder: (_, i) {
        final a = _agents[i];
        return ListTile(
          title: Text(a['alias'] ?? ''),
          subtitle: Text('Owner: ${a['owner_id']} | Voice: ${(a['voice_id'] ?? '').toString().substring(0, 20)}...'),
          trailing: PopupMenuButton<String>(
            onSelected: (action) {
              if (action == 'grant') _grant(a['id']);
            },
            itemBuilder: (_) => [
              const PopupMenuItem(value: 'grant', child: Text('Grant to user')),
              ..._users.map((u) => PopupMenuItem(
                    value: 'revoke_${u['username']}',
                    child: Text('Revoke from ${u['username']}'),
                  )),
            ],
          ),
        );
      },
    );
  }

  Widget _buildUsersTab() {
    return ListView.builder(
      itemCount: _users.length,
      itemBuilder: (_, i) {
        final u = _users[i];
        return ListTile(
          leading: Icon(u['role'] == 'admin' ? Icons.shield : Icons.person),
          title: Text(u['username'] ?? ''),
          subtitle: Text('Role: ${u['role']}'),
        );
      },
    );
  }
}
