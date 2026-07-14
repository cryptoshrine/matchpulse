import type { LiveNotification, LiveNotificationType } from '@/types/api';
import { MintMomentButton } from './MintMomentButton';

interface NarrativeFeedProps {
  notifications: LiveNotification[];
}

const ICONS: Record<LiveNotificationType, string> = {
  goal: '⚽',
  card: '🟨',
  penalty: '🥅',
  var: '📺',
  halftime: '⏸️',
  fulltime: '🏁',
  tactical_shift: '♟️',
  momentum_shift: '⚡',
  event_amendment: '📝',
};

const MINTABLE_NOTIFICATION_TYPES = new Set<LiveNotificationType>([
  'goal',
  'penalty',
  'event_amendment',
]);

function sourceEventType(notificationType: LiveNotificationType): string {
  return notificationType === 'event_amendment' ? 'Event Amendment' : 'Shot';
}

export function NarrativeFeed({ notifications }: NarrativeFeedProps) {
  return (
    <section className="border-4 border-black bg-white p-4 shadow-[5px_5px_0px_0px_rgba(0,0,0,1)]">
      <h2 className="mb-3 text-xl font-black uppercase">Live narrative</h2>
      <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1" aria-live="polite">
        {notifications.length === 0 ? (
          <p className="border-2 border-dashed border-black p-5 text-center font-bold text-gray-600">
            Start a replay to see the match story unfold.
          </p>
        ) : (
          notifications.map((notification, index) => (
            <article
              key={`${notification.event_id ?? notification.timestamp}-${index}`}
              className="flex gap-3 border-2 border-black bg-gray-50 p-3"
            >
              <span className="text-2xl" aria-hidden="true">
                {notification.notification_type === 'card' && notification.card_color === 'red'
                  ? '🟥'
                  : ICONS[notification.notification_type]}
              </span>
              <div>
                <p className="text-xs font-black uppercase text-gray-500">
                  {notification.minute !== undefined ? `${notification.minute}' · ` : ''}
                  {notification.notification_type.replace('_', ' ')}
                </p>
                <p className="font-bold">{notification.message}</p>
                {MINTABLE_NOTIFICATION_TYPES.has(notification.notification_type) &&
                notification.event_id &&
                notification.minute !== undefined ? (
                  <MintMomentButton
                    matchId={notification.match_id}
                    eventId={notification.event_id}
                    eventType={sourceEventType(notification.notification_type)}
                    minute={notification.minute}
                    description={notification.message}
                  />
                ) : null}
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  );
}
