import { useState } from 'react';
import type { PlanPhase } from '../../api/types';
import { StepRow } from './StepRow';
import { StepEditor } from './StepEditor';
import styles from './PhaseAccordion.module.css';

interface PhaseAccordionProps {
  phase: PlanPhase;
  cardId: number;
  editingStep: { cardId: number; stepIndex: number } | null;
  onApproveStep: (stepIndex: number) => void;
  onSkipStep: (stepIndex: number) => void;
  onEditStep: (stepIndex: number) => void;
  onSaveStep: (stepIndex: number, draftContent: string) => void;
  onCancelEdit: () => void;
}

export function PhaseAccordion({
  phase,
  cardId,
  editingStep,
  onApproveStep,
  onSkipStep,
  onEditStep,
  onSaveStep,
  onCancelEdit,
}: PhaseAccordionProps) {
  const [open, setOpen] = useState(true);

  const completedCount = phase.steps.filter(
    (s) => s.status === 'completed' || s.status === 'approved' || s.status === 'skipped',
  ).length;

  return (
    <div className={styles.phase}>
      <button
        className={styles.phaseHeader}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className={styles.chevron}>{open ? '▾' : '▸'}</span>
        <span className={styles.phaseName}>{phase.name}</span>
        <span className={styles.phaseProgress}>
          {completedCount}/{phase.steps.length}
        </span>
      </button>

      {open && (
        <div className={styles.phaseBody}>
          {phase.steps.map((step) => {
            const isEditingThis =
              editingStep?.cardId === cardId && editingStep?.stepIndex === step.index;

            return (
              <div key={step.index}>
                <StepRow
                  step={step}
                  isEditing={isEditingThis}
                  onApprove={() => onApproveStep(step.index)}
                  onSkip={() => onSkipStep(step.index)}
                  onEdit={() => onEditStep(step.index)}
                />
                {isEditingThis && (
                  <StepEditor
                    step={step}
                    onSave={(draftContent) => onSaveStep(step.index, draftContent)}
                    onCancel={onCancelEdit}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
