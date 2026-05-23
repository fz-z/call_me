import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../models/agent.dart';
import 'call_screen.dart';
import 'agent_list_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  List<VoiceAgent> _agents = [];
  VoiceAgent? _selectedAgent;
  bool _loading = true;
  int _currentIndex = 0;

  @override
  void initState() {
    super.initState();
    _loadAgents();
  }

  Future<void> _loadAgents() async {
    final api = context.read<ApiService>();
    try {
      final agents = await api.listAgents();
      setState(() {
        _agents = agents;
        _loading = false;
        if (_selectedAgent == null && agents.isNotEmpty) _selectedAgent = agents.first;
      });
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  Future<void> _startCall() async {
    if (_selectedAgent == null) return;
    final api = context.read<ApiService>();
    try {
      final result = await api.getCallToken(_selectedAgent!.id);
      if (mounted) {
        Navigator.push(context, MaterialPageRoute(
          builder: (_) => CallScreen(
            agent: _selectedAgent!,
            token: result['token']!,
            roomUrl: result['room_url']!,
          ),
        ));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Call failed: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      _buildHome(),
      const AgentListScreen(),
      const SettingsScreen(),
    ];

    return Scaffold(
      appBar: AppBar(title: const Text('call_me')),
      body: screens[_currentIndex],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (i) => setState(() => _currentIndex = i),
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: 'Home'),
          BottomNavigationBarItem(icon: Icon(Icons.person), label: 'Agents'),
          BottomNavigationBarItem(icon: Icon(Icons.settings), label: 'Settings'),
        ],
      ),
    );
  }

  Widget _buildHome() {
    return Center(
      child: _loading
          ? const CircularProgressIndicator()
          : Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.smart_toy, size: 80, color: Colors.blue),
                  const SizedBox(height: 16),
                  if (_agents.isEmpty)
                    const Text('No agents available', style: TextStyle(fontSize: 16, color: Colors.grey))
                  else ...[
                    DropdownButton<VoiceAgent>(
                      value: _selectedAgent,
                      isExpanded: true,
                      items: _agents.map((a) => DropdownMenuItem(value: a, child: Text(a.alias))).toList(),
                      onChanged: (a) => setState(() => _selectedAgent = a),
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: ElevatedButton.icon(
                        onPressed: _startCall,
                        icon: const Icon(Icons.call, size: 28),
                        label: const Text('Start Call', style: TextStyle(fontSize: 18)),
                      ),
                    ),
                  ],
                ],
              ),
            ),
    );
  }
}
