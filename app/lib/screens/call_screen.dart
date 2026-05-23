import 'package:flutter/material.dart';
import 'package:livekit_client/livekit_client.dart' hide Agent;
import '../models/agent.dart';

class CallScreen extends StatefulWidget {
  final VoiceAgent agent;
  final String token;
  final String roomUrl;

  const CallScreen({super.key, required this.agent, required this.token, required this.roomUrl});

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  Room? _room;
  LocalAudioTrack? _localTrack;
  bool _connecting = true;
  final _duration = Stopwatch();

  @override
  void initState() {
    super.initState();
    _connect();
  }

  Future<void> _connect() async {
    final room = Room();
    room.events.listen((event) {
      if (mounted) setState(() => _connecting = false);
    });

    try {
      await room.connect(widget.roomUrl, widget.token);

      // Publish local microphone so the agent can hear the user
      try {
        final track = LocalAudioTrack.create();
        await room.localParticipant!.publishAudioTrack(track);
        _localTrack = track;
      } catch (e) {
        // Microphone might not be available (e.g., web permissions)
        debugPrint('Failed to publish microphone: $e');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Microphone unavailable. Agent cannot hear you.')),
          );
        }
      }

      _duration.start();
      setState(() {
        _room = room;
        _connecting = false;
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Connection failed: $e')));
        Navigator.pop(context);
      }
    }
  }

  Future<void> _hangup() async {
    await _localTrack?.stop();
    await _room?.disconnect();
    _duration.stop();
    if (mounted) Navigator.pop(context);
  }

  @override
  void dispose() {
    _localTrack?.stop();
    _room?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(widget.agent.alias, style: const TextStyle(color: Colors.white, fontSize: 20)),
            const SizedBox(height: 16),
            _connecting
                ? const CircularProgressIndicator(color: Colors.white)
                : const Icon(Icons.mic, size: 64, color: Colors.green),
            const SizedBox(height: 16),
            StreamBuilder(
              stream: Stream.periodic(const Duration(seconds: 1)),
              builder: (_, __) => Text(
                '${_duration.elapsed.inMinutes}:${(_duration.elapsed.inSeconds % 60).toString().padLeft(2, '0')}',
                style: const TextStyle(color: Colors.white70, fontSize: 24),
              ),
            ),
            const SizedBox(height: 48),
            FloatingActionButton(
              onPressed: _hangup,
              backgroundColor: Colors.red,
              child: const Icon(Icons.call_end, color: Colors.white, size: 32),
            ),
          ],
        ),
      ),
    );
  }
}
