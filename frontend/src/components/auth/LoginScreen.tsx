import React, { useState } from 'react';
import { ApiError, HttpChronosApiClient, setSession } from '@/api/chronosApi';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

interface LoginScreenProps {
  client: HttpChronosApiClient;
  /** The previous session's token was refused */
  expired: boolean;
}

const inputClass = 'w-full rounded-md border border-input bg-card px-3 py-2';

/** http mode: POST /auth/login, then the session (token and role) is kept by setSession. */
export const LoginScreen: React.FC<LoginScreenProps> = ({ client, expired }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      setSession(await client.login(username, password));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? 'Incorrect username or password.' : (err as Error).message);
      setPending(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-md px-4 py-16">
        <Card data-testid="login-screen">
          <CardHeader>
            <CardTitle className="text-2xl">Chronos</CardTitle>
            <CardDescription>Log in with your Chronos account to see and manage the department timetable.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="space-y-4">
              {expired && !error && (
                <p role="alert" data-testid="session-expired" className="text-destructive">
                  Session expired, please log in again
                </p>
              )}
              {error && (
                <p role="alert" data-testid="login-error" className="text-destructive">
                  {error}
                </p>
              )}
              <label className="block space-y-1 font-semibold">
                <span>Username</span>
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  required
                  maxLength={64}
                  className={inputClass}
                />
              </label>
              <label className="block space-y-1 font-semibold">
                <span>Password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  className={inputClass}
                />
              </label>
              <Button type="submit" className="w-full" disabled={pending} data-testid="login-button">
                {pending ? 'Logging in…' : 'Log in'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
