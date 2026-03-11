import { useState } from 'react';
import { usePlan, useUpdateStep, useApproveRemaining, useExecutePlan, useRegeneratePlan } from '../../hooks/usePlan';
import { useUIStore } from '../../stores/ui';
import { Button } from '../../components/Button';
import { PhaseAccordion } from './PhaseAccordion';
import styles from './PlanView.module.css';

interface PlanViewProps {
  cardId: number;
}

export function PlanView({ cardId }: PlanViewProps) {
  const { data, isLoading, error } = usePlan(cardId);
  const editingStep = useUIStore((s) => s.editingStep);
  const setEditingStep = useUIStore((s) => s.setEditingStep);

  const updateStep = useUpdateStep(cardId);
  const approveRemaining = useApproveRemaining(cardId);
  const executePlan = useExecutePlan(cardId);
  const regeneratePlan = useRegeneratePlan(cardId);

  const [feedbackText, setFeedbackText] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);

  if (isLoading) {
    return <div className={styles.loading}>Loading plan...</div>;
  }

  if (error || !data) {
    return <div className={styles.empty}>No plan available for this card.</div>;
  }

  const { plan } = data;

  const allSteps = plan.phases.flatMap((p) => p.steps);
  const pendingSteps = allSteps.filter((s) => s.status === 'pending');
  const isExecuting = plan.status === 'executing';
  const isCompleted = plan.status === 'completed';

  function handleApproveStep(stepIndex: number) {
    updateStep.mutate({ stepIndex, status: 'approved' });
  }

  function handleSkipStep(stepIndex: number) {
    updateStep.mutate({ stepIndex, status: 'skipped' });
  }

  function handleEditStep(stepIndex: number) {
    setEditingStep({ cardId, stepIndex });
  }

  function handleSaveStep(stepIndex: number, draftContent: string) {
    updateStep.mutate({ stepIndex, status: 'edited', draft_content: draftContent });
    setEditingStep(null);
  }

  function handleCancelEdit() {
    setEditingStep(null);
  }

  function handleApproveAll() {
    approveRemaining.mutate(0);
  }

  function handleExecute() {
    executePlan.mutate();
  }

  function handleRegenerate() {
    if (!feedbackText.trim()) return;
    regeneratePlan.mutate(feedbackText.trim());
    setFeedbackText('');
    setShowFeedback(false);
  }

  return (
    <div className={styles.planView}>
      <div className={styles.planHeader}>
        <div className={styles.planMeta}>
          <span className={styles.playbookId}>{plan.playbook_id}</span>
          <span className={styles.confidence}>
            {Math.round(plan.confidence * 100)}% confidence
          </span>
          <span className={`${styles.planStatus} ${styles[plan.status]}`}>{plan.status}</span>
        </div>

        {!isCompleted && !isExecuting && (
          <div className={styles.planActions}>
            {pendingSteps.length > 0 && (
              <Button
                label={`Approve All (${pendingSteps.length})`}
                onClick={handleApproveAll}
                variant="mint"
                disabled={approveRemaining.isPending}
              />
            )}
            <Button
              label="Execute"
              onClick={handleExecute}
              variant="primary"
              disabled={executePlan.isPending || pendingSteps.length > 0}
            />
            <Button
              label="Regenerate"
              onClick={() => setShowFeedback((v) => !v)}
              variant="ghost"
            />
          </div>
        )}

        {isExecuting && (
          <div className={styles.executingBadge}>Executing...</div>
        )}

        {isCompleted && (
          <div className={styles.completedBadge}>Plan completed</div>
        )}
      </div>

      {showFeedback && (
        <div className={styles.feedbackRow}>
          <input
            className={styles.feedbackInput}
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            placeholder="Describe what to change in the plan..."
            onKeyDown={(e) => e.key === 'Enter' && handleRegenerate()}
          />
          <Button
            label="Submit"
            onClick={handleRegenerate}
            variant="primary"
            disabled={!feedbackText.trim() || regeneratePlan.isPending}
          />
          <Button label="Cancel" onClick={() => setShowFeedback(false)} variant="ghost" />
        </div>
      )}

      <div className={styles.phases}>
        {plan.phases.map((phase) => (
          <PhaseAccordion
            key={phase.name}
            phase={phase}
            cardId={cardId}
            editingStep={editingStep}
            onApproveStep={handleApproveStep}
            onSkipStep={handleSkipStep}
            onEditStep={handleEditStep}
            onSaveStep={handleSaveStep}
            onCancelEdit={handleCancelEdit}
          />
        ))}
      </div>
    </div>
  );
}
