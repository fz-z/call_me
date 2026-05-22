class Agent {
  final String id;
  final String alias;
  final String voiceId;
  final String systemPrompt;
  final String ownerId;
  final String createdAt;

  Agent({
    required this.id,
    required this.alias,
    required this.voiceId,
    required this.systemPrompt,
    required this.ownerId,
    required this.createdAt,
  });

  factory Agent.fromJson(Map<String, dynamic> json) {
    return Agent(
      id: json['id'],
      alias: json['alias'],
      voiceId: json['voice_id'],
      systemPrompt: json['system_prompt'],
      ownerId: json['owner_id'],
      createdAt: json['created_at'],
    );
  }
}

class User {
  final String id;
  final String username;
  final String role;
  final String createdAt;

  User({required this.id, required this.username, required this.role, required this.createdAt});

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
      id: json['id'],
      username: json['username'],
      role: json['role'],
      createdAt: json['created_at'],
    );
  }
}
