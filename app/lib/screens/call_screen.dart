import 'package:flutter/material.dart';
import 'package:livekit_client/livekit_client.dart' hide Agent;
import '../models/agent.dart';

enum CallState { connecting, ringing, active }

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
  CallState _state = CallState.connecting;
  final _duration = Stopwatch();
  Function()? _cancelTrackSub;
  Function()? _cancelAgentDisconnectSub;
  bool _agentEndedCall = false;

  @override
  void initState() {
    super.initState();
    _connect();
  }

  Future<void> _connect() async {
    final room = Room();

    // Listen for the agent's first audio — once received, transition to active
    _cancelTrackSub = room.events.listen((event) {
      if (event is TrackSubscribedEvent) {
        if (event.publication.kind == TrackType.AUDIO &&
            event.participant is RemoteParticipant) {
          _cancelTrackSub?.call();
          _cancelTrackSub = null;
          if (_state == CallState.ringing && mounted) {
            setState(() {
              _state = CallState.active;
              _duration.start();
            });
          }
        }
      }
    });

    // Listen for agent (remote participant) disconnecting
    _cancelAgentDisconnectSub = room.events.listen((event) {
      if (event is ParticipantDisconnectedEvent &&
          event.participant is RemoteParticipant &&
          !_agentEndedCall) {
        _agentEndedCall = true;
        _duration.stop();
        if (mounted) {
          setState(() {});
          // Auto-dismiss after 3 seconds
          Future.delayed(const Duration(seconds: 3), () {
            if (mounted) Navigator.pop(context);
          });
        }
      }
    });

    try {
      await room.connect(widget.roomUrl, widget.token);

      // Publish local microphone
      try {
        final track = await LocalAudioTrack.create();
        await room.localParticipant!.publishAudioTrack(track);
        _localTrack = track;
      } catch (_) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Microphone unavailable. Agent cannot hear you.')),
          );
        }
      }

      setState(() {
        _room = room;
        _state = CallState.ringing;
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
    _cancelTrackSub?.call();
    _cancelAgentDisconnectSub?.call();
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
            if (_state == CallState.connecting) ...[
              const CircularProgressIndicator(color: Colors.white),
              const SizedBox(height: 12),
              const Text('正在连接...', style: TextStyle(color: Colors.white70, fontSize: 14)),
            ] else if (_state == CallState.ringing) ...[
              const CircularProgressIndicator(color: Colors.white),
              const SizedBox(height: 12),
              const Text('等待对方接听...', style: TextStyle(color: Colors.white70, fontSize: 14)),
            ] else if (_agentEndedCall) ...[
              const Icon(Icons.call_end, size: 64, color: Colors.red),
              const SizedBox(height: 12),
              const Text('通话结束', style: TextStyle(color: Colors.white70, fontSize: 20)),
              const SizedBox(height: 36),
              FloatingActionButton(
                onPressed: () => Navigator.pop(context),
                backgroundColor: Colors.grey,
                child: const Icon(Icons.close, color: Colors.white, size: 32),
              ),
            ] else ...[
              const Icon(Icons.mic, size: 64, color: Colors.green),
              const SizedBox(height: 12),
              StreamBuilder(
                stream: Stream.periodic(const Duration(seconds: 1)),
                builder: (_, __) => Text(
                  '${_duration.elapsed.inMinutes}:${(_duration.elapsed.inSeconds % 60).toString().padLeft(2, '0')}',
                  style: const TextStyle(color: Colors.white70, fontSize: 24),
                ),
              ),
              const SizedBox(height: 36),
              FloatingActionButton(
                onPressed: _hangup,
                backgroundColor: Colors.red,
                child: const Icon(Icons.call_end, color: Colors.white, size: 32),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
