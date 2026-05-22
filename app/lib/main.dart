import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'services/api_service.dart';
import 'screens/login_screen.dart';
import 'screens/home_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final api = ApiService();
  await api.init();

  runApp(
    Provider<ApiService>.value(value: api, child: const CallMeApp()),
  );
}

class CallMeApp extends StatelessWidget {
  const CallMeApp({super.key});

  @override
  Widget build(BuildContext context) {
    final api = context.read<ApiService>();
    final loggedIn = api.token != null;

    return MaterialApp(
      title: 'call_me',
      theme: ThemeData(primarySwatch: Colors.blue, useMaterial3: true),
      home: loggedIn ? const HomeScreen() : const LoginScreen(),
    );
  }
}
