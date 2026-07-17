import { useEffect, useState } from 'react';
import type { LiveNotification } from '@/types/api';

interface BannerStyle {
  emoji: string;
  accentClass: string;
}

const DEFAULT_STYLE: BannerStyle = { emoji: '⚡', accentClass: 'bg-brutal-pink' };

const BANNER_STYLES: Record<string, BannerStyle> = {
  goal: { emoji: '⚽', accentClass: 'bg-brutal-green' },
  penalty: { emoji: '🎯', accentClass: 'bg-brutal-yellow' },
  var: { emoji: '⚖️', accentClass: 'bg-brutal-blue' },
  event_amendment: { emoji: '✅', accentClass: 'bg-brutal-green' },
  fulltime: { emoji: '🏁', accentClass: 'bg-brutal-yellow' },
  momentum_shift: { emoji: '⚡', accentClass: 'bg-brutal-pink' },
  card_red: { emoji: '🟥', accentClass: 'bg-brutal-red' },
};

function resolveStyle(alert: LiveNotification): BannerStyle {
  if (alert.notification_type === 'card') {
    return alert.card_color === 'red' ? BANNER_STYLES.card_red : DEFAULT_STYLE;
  }
  return BANNER_STYLES[alert.notification_type] ?? DEFAULT_STYLE;
}

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
  const style = resolveStyle(alert);

  return (
    <div
      className={`border-4 border-black ${style.accentClass} p-4 text-center text-lg font-black uppercase shadow-[6px_6px_0px_0px_rgba(0,0,0,1)]`}
      role="alert"
    >
      {style.emoji} {alert.message}
    </div>
  );
}
