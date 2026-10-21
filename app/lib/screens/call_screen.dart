import 'dart:ui' show ImageFilter;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:livekit_client/livekit_client.dart' hide Agent;

import '../models/agent.dart';

enum CallState { connecting, ringing, active }

class CallScreen extends StatefulWidget {
  final VoiceAgent agent;
  final String token;
  final String roomUrl;

  const CallScreen(
      {super.key,
      required this.agent,
      required this.token,
      required this.roomUrl});

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen>
    with SingleTickerProviderStateMixin {
  Room? _room;
  LocalAudioTrack? _localTrack;
  CallState _state = CallState.connecting;
  final _duration = Stopwatch();
  Function()? _cancelTrackSub;
  Function()? _cancelAgentDisconnectSub;
  bool _agentEndedCall = false;
  bool _agentAudioReady = false;
  bool _micOk = false;
  bool _muted = false;
  bool _speakerOn = false;
  String _micError = '';
  late final AnimationController _pulseController;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);
    _connect();
  }

  Future<void> _connect() async {
    final room = Room();

    // The agent may publish audio before the mic/ringing state is ready.
    // Keep a flag and activate as soon as both conditions are true.
    _cancelTrackSub = room.events.listen((event) {
      if (event is TrackSubscribedEvent) {
        if (event.publication.kind == TrackType.AUDIO &&
            event.participant is RemoteParticipant) {
          _cancelTrackSub?.call();
          _cancelTrackSub = null;
          _agentAudioReady = true;
          _activateIfReady();
        }
      }
    });

    _cancelAgentDisconnectSub = room.events.listen((event) {
      if (event is ParticipantDisconnectedEvent &&
          event.participant is RemoteParticipant &&
          !_agentEndedCall) {
        _agentEndedCall = true;
        _duration.stop();
        if (mounted) {
          setState(() {});
          Future.delayed(const Duration(seconds: 3), () {
            if (mounted) Navigator.pop(context);
          });
        }
      }
    });

    try {
      await room.connect(widget.roomUrl, widget.token);

      try {
        final track = await LocalAudioTrack.create();
        await room.localParticipant!.publishAudioTrack(track);
        _localTrack = track;
        _micOk = true;
      } catch (e) {
        _micError = '麦克风不可用，请检查权限';
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text('麦克风错误: $e'),
                duration: const Duration(seconds: 5)),
          );
        }
      }

      setState(() {
        _room = room;
        _state = CallState.ringing;
      });
      _activateIfReady();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('连接失败，请稍后重试')),
        );
        Navigator.pop(context);
      }
    }
  }

  void _activateIfReady() {
    if (!mounted ||
        !_agentAudioReady ||
        _agentEndedCall ||
        _state != CallState.ringing) {
      return;
    }
    setState(() {
      _state = CallState.active;
      _duration.start();
    });
  }

  Future<void> _toggleMute() async {
    final track = _localTrack;
    if (track == null) return;
    try {
      if (_muted) {
        await track.unmute(stopOnMute: false);
      } else {
        await track.mute(stopOnMute: false);
      }
      if (mounted) setState(() => _muted = !_muted);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('麦克风切换失败')),
        );
      }
    }
  }

  Future<void> _toggleSpeaker() async {
    if (kIsWeb || !Hardware.instance.canSwitchSpeakerphone) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('当前设备不支持切换免提')),
        );
      }
      return;
    }
    try {
      await Hardware.instance.setSpeakerphoneOn(!_speakerOn);
      if (mounted) setState(() => _speakerOn = !_speakerOn);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('免提切换失败')),
        );
      }
    }
  }

  Future<void> _hangup() async {
    await _localTrack?.stop();
    await _room?.disconnect();
    _duration.stop();
    if (mounted) Navigator.pop(context);
  }

  String _photoFullUrl(String path) {
    if (path.startsWith('http')) return path;
    return '${Uri.base.origin}$path';
  }

  @override
  void dispose() {
    _cancelTrackSub?.call();
    _cancelAgentDisconnectSub?.call();
    _localTrack?.stop();
    _room?.dispose();
    _pulseController.dispose();
    super.dispose();
  }

  Widget _buildBackground() {
    final photo = widget.agent.photoUrl;
    if (photo != null && photo.isNotEmpty) {
      return Stack(
        fit: StackFit.expand,
        children: [
          ImageFiltered(
            imageFilter: ImageFilter.blur(sigmaX: 28, sigmaY: 28),
            child: Image.network(
              _photoFullUrl(photo),
              fit: BoxFit.cover,
              errorBuilder: (_, __, ___) =>
                  const ColoredBox(color: Color(0xFF18181B)),
            ),
          ),
          const ColoredBox(color: Color.fromRGBO(0, 0, 0, 0.48)),
        ],
      );
    }
    return const DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xFF2A2A2E), Color(0xFF111113)],
        ),
      ),
    );
  }

  Widget _initialAvatar() {
    final alias = widget.agent.alias.trim();
    return Container(
      width: 128,
      height: 128,
      color: const Color(0xFF2C2C2E),
      alignment: Alignment.center,
      child: Text(
        alias.isEmpty ? '?' : alias.substring(0, 1),
        style: const TextStyle(
          color: Colors.white,
          fontSize: 48,
          fontWeight: FontWeight.w500,
        ),
      ),
    );
  }

  Widget _buildAvatar() {
    final photo = widget.agent.photoUrl;
    final Widget content = (photo != null && photo.isNotEmpty)
        ? Image.network(
            _photoFullUrl(photo),
            width: 128,
            height: 128,
            fit: BoxFit.cover,
            errorBuilder: (_, __, ___) => _initialAvatar(),
          )
        : _initialAvatar();
    final showPulse = _state != CallState.active && !_agentEndedCall;

    return SizedBox(
      width: 168,
      height: 168,
      child: Stack(
        alignment: Alignment.center,
        children: [
          if (showPulse)
            AnimatedBuilder(
              animation: _pulseController,
              builder: (_, __) {
                final value = _pulseController.value;
                return Container(
                  width: 138 + 26 * value,
                  height: 138 + 26 * value,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: Color.fromRGBO(255, 255, 255, 0.08 + 0.10 * value),
                      width: 2,
                    ),
                  ),
                );
              },
            ),
          Container(
            width: 128,
            height: 128,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: const Color(0x55FFFFFF), width: 3),
              boxShadow: const [
                BoxShadow(
                  color: Color.fromRGBO(0, 0, 0, 0.35),
                  blurRadius: 24,
                  offset: Offset(0, 8),
                ),
              ],
            ),
            child: ClipOval(child: content),
          ),
        ],
      ),
    );
  }

  Widget _buildStatus() {
    if (_agentEndedCall) {
      return const Text(
        '通话结束',
        style: TextStyle(color: Colors.white70, fontSize: 16),
      );
    }
    if (_state == CallState.active) {
      return StreamBuilder(
        stream: Stream.periodic(const Duration(seconds: 1)),
        builder: (_, __) => Text(
          '${_duration.elapsed.inMinutes.toString().padLeft(2, '0')}:'
          '${(_duration.elapsed.inSeconds % 60).toString().padLeft(2, '0')}',
          style: const TextStyle(
            color: Colors.white70,
            fontSize: 18,
            fontFeatures: [FontFeature.tabularFigures()],
          ),
        ),
      );
    }
    return Text(
      _state == CallState.connecting ? '正在连接…' : '等待对方接听…',
      style: const TextStyle(color: Colors.white70, fontSize: 16),
    );
  }

  Widget _buildActions() {
    if (_agentEndedCall) {
      return Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.call_end, color: Color(0xFFE5484D), size: 52),
          const SizedBox(height: 12),
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text(
              '关闭',
              style: TextStyle(color: Colors.white70, fontSize: 16),
            ),
          ),
        ],
      );
    }
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _CallAction(
          icon: _muted ? Icons.mic_off : Icons.mic,
          label: _muted ? '已静音' : '静音',
          active: _muted,
          onTap: _localTrack == null ? null : _toggleMute,
        ),
        const SizedBox(width: 44),
        _CallAction(
          icon: _speakerOn ? Icons.volume_up : Icons.volume_off,
          label: '免提',
          active: _speakerOn,
          onTap: _toggleSpeaker,
        ),
        const SizedBox(width: 44),
        _CallAction(
          icon: Icons.call_end,
          label: '挂断',
          background: const Color(0xFFE5484D),
          iconColor: Colors.white,
          size: 68,
          onTap: _hangup,
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          _buildBackground(),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Column(
                children: [
                  const SizedBox(height: 18),
                  const Text(
                    '语音通话',
                    style: TextStyle(
                      color: Colors.white54,
                      fontSize: 14,
                      letterSpacing: 2,
                    ),
                  ),
                  const Spacer(flex: 2),
                  _buildAvatar(),
                  const SizedBox(height: 20),
                  Text(
                    widget.agent.alias,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 24,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 10),
                  _buildStatus(),
                  if (_micError.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      _micError,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: Color(0xFFFF8A8A),
                        fontSize: 12,
                      ),
                    ),
                  ],
                  const Spacer(flex: 3),
                  _buildActions(),
                  const SizedBox(height: 36),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CallAction extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final bool active;
  final Color background;
  final Color iconColor;
  final double size;

  const _CallAction({
    required this.icon,
    required this.label,
    required this.onTap,
    this.active = false,
    this.background = const Color.fromRGBO(255, 255, 255, 0.14),
    this.iconColor = Colors.white,
    this.size = 60,
  });

  @override
  Widget build(BuildContext context) {
    final disabled = onTap == null;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Opacity(
          opacity: disabled ? 0.35 : 1,
          child: Material(
            color: active ? Colors.white : background,
            shape: const CircleBorder(),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: onTap,
              child: SizedBox(
                width: size,
                height: size,
                child: Icon(
                  icon,
                  color: active ? Colors.black87 : iconColor,
                  size: size * 0.46,
                ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          label,
          style: const TextStyle(color: Colors.white70, fontSize: 12),
        ),
      ],
    );
  }
}
