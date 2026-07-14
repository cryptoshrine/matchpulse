import { useEffect, useState } from 'react';
import type { LiveNotification } from '@/types/api';

interface AlertBannerProps {
  alert: LiveNotification | null;
}

export function AlertBanner({ alert }: AlertBannerProps) {
  const [visible, setVisible] = useState(alert !== null);

  useEffect(() => {
    if (alert === null) {
      setVisible(false);
      return;
    }
    setVisible(true);
    const timeout = window.setTimeout(() => setVisible(false), 15_000);
    return () => window.clearTimeout(timeout);
  }, [alert]);

  if (!alert || !visible) return null;

  return (
    <div className="border-4 border-black bg-brutal-pink p-4 text-center text-lg font-black uppercase shadow-[6px_6px_0px_0px_rgba(0,0,0,1)]" role="alert">
      ⚡ {alert.message}
    </div>
  );
}
