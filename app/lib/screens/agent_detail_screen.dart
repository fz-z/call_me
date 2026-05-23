import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../models/agent.dart';

class AgentDetailScreen extends StatefulWidget {
  final VoiceAgent agent;

  const AgentDetailScreen({super.key, required this.agent});

  @override
  State<AgentDetailScreen> createState() => _AgentDetailScreenState();
}

class _AgentDetailScreenState extends State<AgentDetailScreen> {
  late TextEditingController _alias;
  late TextEditingController _systemPrompt;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _alias = TextEditingController(text: widget.agent.alias);
    _systemPrompt = TextEditingController(text: widget.agent.systemPrompt);
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      final api = context.read<ApiService>();
      await api.updateAgent(widget.agent.id, _alias.text.trim(), _systemPrompt.text.trim());
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Saved')));
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Save failed: $e')));
      }
    } finally {
      setState(() => _saving = false);
    }
  }

  @override
  void dispose() {
    _alias.dispose();
    _systemPrompt.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Edit Agent'), actions: [
        TextButton(onPressed: _saving ? null : _save, child: const Text('Save')),
      ]),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Alias', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            TextField(controller: _alias, decoration: const InputDecoration(hintText: 'Agent name')),
            const SizedBox(height: 24),
            const Text('Personality / System Prompt', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            TextField(
              controller: _systemPrompt,
              maxLines: 8,
              decoration: const InputDecoration(
                hintText: 'Describe the personality...',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 24),
            Text('Voice: ${widget.agent.voiceId}', style: const TextStyle(color: Colors.grey, fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
