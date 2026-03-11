import { useState } from 'react';
import type { PlanStep } from '../../api/types';
import { Button } from '../../components/Button';
import styles from './StepEditor.module.css';

interface StepEditorProps {
  step: PlanStep;
  onSave: (draftContent: string) => void;
  onCancel: () => void;
}

export function StepEditor({ step, onSave, onCancel }: StepEditorProps) {
  const [draft, setDraft] = useState(step.draft_content ?? '');
  const [feedback, setFeedback] = useState('');

  function handleSave() {
    onSave(draft);
  }

  return (
    <div className={styles.editor}>
      <div className={styles.editorHeader}>
        <span className={styles.editorTitle}>Edit Step {step.index + 1}</span>
        <span className={styles.editorTool}>{step.tool}</span>
      </div>

      {step.draft_content !== null && (
        <div className={styles.field}>
          <label className={styles.label}>Draft Content</label>
          <textarea
            className={styles.textarea}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={6}
            placeholder="Edit draft content..."
          />
        </div>
      )}

      <div className={styles.field}>
        <label className={styles.label}>Feedback for regeneration (optional)</label>
        <input
          className={styles.input}
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="e.g. Use a different subject line..."
        />
      </div>

      <div className={styles.editorActions}>
        <Button label="Save" onClick={handleSave} variant="primary" />
        <Button label="Cancel" onClick={onCancel} variant="ghost" />
      </div>
    </div>
  );
}
