import { createContext, useCallback, useContext, type ReactNode } from 'react';
import {
  appendEvent,
  completeSession as completeSessionApi,
  createSession,
  type InputSummary,
  type SessionEvent,
  type SessionType,
} from '../api/sessionApi';

interface SessionContextValue {
  startSession: (type: SessionType, inputSummary: InputSummary) => Promise<string>;
  emitEvent: (sessionId: string, event: SessionEvent) => Promise<void>;
  completeSession: (sessionId: string, status: 'complete' | 'error' | 'interrupted', snapshot?: unknown) => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const startSession = useCallback(async (type: SessionType, inputSummary: InputSummary): Promise<string> => {
    const { session_id } = await createSession(type, inputSummary);
    return session_id;
  }, []);

  const emitEvent = useCallback(async (sessionId: string, event: SessionEvent): Promise<void> => {
    await appendEvent(sessionId, event);
  }, []);

  const completeSession = useCallback(async (
    sessionId: string,
    status: 'complete' | 'error' | 'interrupted',
    snapshot?: unknown,
  ): Promise<void> => {
    await completeSessionApi(sessionId, status, snapshot);
  }, []);

  return (
    <SessionContext.Provider value={{ startSession, emitEvent, completeSession }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside <SessionProvider>');
  return ctx;
}
