import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../models/agent.dart';
import 'agent_detail_screen.dart';

class AgentListScreen extends StatefulWidget {
  const AgentListScreen({super.key});

  @override
  State<AgentListScreen> createState() => _AgentListScreenState();
}

class _AgentListScreenState extends State<AgentListScreen> {
  List<VoiceAgent> _agents = [];
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
      _agents = await api.listAgents();
    } catch (_) {}
    setState(() => _loading = false);
  }

  Future<void> _openDetail(VoiceAgent agent) async {
    final updated = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => AgentDetailScreen(agent: agent)),
    );
    if (updated == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My Agents')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _agents.isEmpty
              ? const Center(child: Text('No agents'))
              : ListView.builder(
                  itemCount: _agents.length,
                  itemBuilder: (_, i) {
                    final a = _agents[i];
                    return ListTile(
                      title: Text(a.alias),
                      subtitle: Text(a.systemPrompt, maxLines: 1, overflow: TextOverflow.ellipsis),
                      trailing: const Icon(Icons.edit),
                      onTap: () => _openDetail(a),
                    );
                  },
                ),
    );
  }
}
