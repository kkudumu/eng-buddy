import type { PlanStep, StepRisk } from '../../api/types';
import { Badge } from '../../components/Badge';
import { Button } from '../../components/Button';
import styles from './StepRow.module.css';

const RISK_BADGE: Record<StepRisk, 'pink' | 'mint' | 'blue' | 'coral' | 'muted'> = {
  low: 'mint',
  medium: 'blue',
  high: 'coral',
};

const STATUS_LABEL: Record<string, string> = {
  pending: 'Pending',
  approved: 'Approved',
  edited: 'Edited',
  skipped: 'Skipped',
  completed: 'Completed',
  failed: 'Failed',
};

interface StepRowProps {
  step: PlanStep;
  isEditing: boolean;
  onApprove: () => void;
  onSkip: () => void;
  onEdit: () => void;
}

export function StepRow({ step, isEditing, onApprove, onSkip, onEdit }: StepRowProps) {
  const isDone = step.status === 'completed' || step.status === 'failed' || step.status === 'skipped';

  return (
    <div className={`${styles.stepRow} ${isDone ? styles.done : ''}`}>
      <div className={styles.stepHeader}>
        <span className={styles.stepIndex}>{step.index + 1}</span>
        <span className={styles.stepSummary}>{step.summary}</span>
        <Badge text={step.risk} color={RISK_BADGE[step.risk] ?? 'muted'} />
        <span className={`${styles.statusChip} ${styles[step.status]}`}>
          {STATUS_LABEL[step.status] ?? step.status}
        </span>
      </div>

      {step.detail && (
        <div className={styles.stepDetail}>{step.detail}</div>
      )}

      {step.draft_content && (
        <pre className={styles.draftContent}>{step.draft_content}</pre>
      )}

      {!isDone && !isEditing && (
        <div className={styles.stepActions}>
          <Button label="Approve" onClick={onApprove} variant="mint" />
          <Button label="Edit" onClick={onEdit} variant="ghost" />
          <Button label="Skip" onClick={onSkip} variant="ghost" />
        </div>
      )}
    </div>
  );
}
