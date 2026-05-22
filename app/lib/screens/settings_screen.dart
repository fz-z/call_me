import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/api_service.dart';
import 'login_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _serverUrl = TextEditingController();
  final _phoneNumber = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    _serverUrl.text = prefs.getString('server_url') ?? 'http://10.0.2.2:8000';
  }

  Future<void> _saveUrl() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_url', _serverUrl.text.trim());
    context.read<ApiService>().setBaseUrl(_serverUrl.text.trim());
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Server URL saved')));
  }

  Future<void> _logout() async {
    await context.read<ApiService>().logout();
    if (mounted) {
      Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LoginScreen()), (_) => false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Server URL', style: TextStyle(fontWeight: FontWeight.bold)),
          TextField(controller: _serverUrl, decoration: const InputDecoration(hintText: 'http://your-server:8000')),
          const SizedBox(height: 8),
          ElevatedButton(onPressed: _saveUrl, child: const Text('Save')),
          const Divider(height: 32),
          const Text('SIP Binding (Admin)', style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          TextField(controller: _phoneNumber, decoration: const InputDecoration(hintText: '+86 138xxxx8888')),
          const SizedBox(height: 8),
          ElevatedButton(onPressed: () {}, child: const Text('Bind')),
          const Spacer(),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(onPressed: _logout, child: const Text('Logout')),
          ),
        ],
      ),
    );
  }
}
