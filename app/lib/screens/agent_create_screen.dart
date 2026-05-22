import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';

class AgentCreateScreen extends StatefulWidget {
  const AgentCreateScreen({super.key});

  @override
  State<AgentCreateScreen> createState() => _AgentCreateScreenState();
}

class _AgentCreateScreenState extends State<AgentCreateScreen> {
  final _alias = TextEditingController();
  final _systemPrompt = TextEditingController();
  String? _filePath;
  String? _fileName;
  bool _loading = false;

  Future<void> _pickFile() async {
    final result = await FilePicker.platform.pickFiles(type: FileType.audio);
    if (result != null && result.files.single.path != null) {
      setState(() {
        _filePath = result.files.single.path!;
        _fileName = result.files.single.name;
      });
    }
  }

  Future<void> _submit() async {
    if (_filePath == null || _alias.text.trim().isEmpty) return;
    setState(() => _loading = true);
    try {
      final api = context.read<ApiService>();
      await api.createAgent(_alias.text.trim(), _systemPrompt.text.trim(), _filePath!);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Agent created!')));
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Failed: $e')));
      }
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Create Agent')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            TextField(controller: _alias, decoration: const InputDecoration(labelText: 'Alias (name)')),
            const SizedBox(height: 12),
            TextField(controller: _systemPrompt, maxLines: 4, decoration: const InputDecoration(labelText: 'Personality / System Prompt')),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: _pickFile,
              icon: const Icon(Icons.audio_file),
              label: Text(_fileName ?? 'Pick audio file (wav/mp3/m4a)'),
            ),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _loading ? null : _submit,
                child: _loading ? const CircularProgressIndicator() : const Text('Create Agent'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
