class VoiceAgent {
  final String id;
  final String alias;
  final String? voicePoolId;
  final String systemPrompt;
  final String ownerId;
  final String createdAt;
  final String runtimeMode;
  final String? provider;
  final String? photoUrl;

  VoiceAgent({
    required this.id,
    required this.alias,
    this.voicePoolId,
    required this.systemPrompt,
    required this.ownerId,
    required this.createdAt,
    this.runtimeMode = 'pipeline',
    this.provider,
    this.photoUrl,
  });

  factory VoiceAgent.fromJson(Map<String, dynamic> json) {
    return VoiceAgent(
      id: json['id'],
      alias: json['alias'],
      voicePoolId: json['voice_pool_id'] as String?,
      systemPrompt: json['system_prompt'],
      ownerId: json['owner_id'],
      createdAt: json['created_at'],
      runtimeMode: json['runtime_mode'] as String? ?? 'pipeline',
      provider: json['provider'] as String?,
      photoUrl: json['photo_url'] as String?,
    );
  }
}

class User {
  final String id;
  final String username;
  final String role;
  final String createdAt;

  User(
      {required this.id,
      required this.username,
      required this.role,
      required this.createdAt});

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
      id: json['id'],
      username: json['username'],
      role: json['role'],
      createdAt: json['created_at'],
    );
  }
}
