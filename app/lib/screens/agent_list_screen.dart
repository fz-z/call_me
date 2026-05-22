import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../models/agent.dart';
import 'agent_create_screen.dart';

class VoiceAgentListScreen extends StatefulWidget {
  const VoiceAgentListScreen({super.key});

  @override
  State<VoiceAgentListScreen> createState() => _VoiceAgentListScreenState();
}

class _VoiceAgentListScreenState extends State<VoiceAgentListScreen> {
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
      _agents = await api.listVoiceAgents();
    } catch (_) {}
    setState(() => _loading = false);
  }

  Future<void> _delete(String id) async {
    final api = context.read<ApiService>();
    await api.deleteVoiceAgent(id);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('VoiceAgents')),
      floatingActionButton: FloatingActionButton(
        onPressed: () async {
          final created = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => const AgentCreateScreen()));
          if (created == true) _load();
        },
        child: const Icon(Icons.add),
      ),
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
                      trailing: IconButton(icon: const Icon(Icons.delete_outline), onPressed: () => _delete(a.id)),
                    );
                  },
                ),
    );
  }
}
