"""
LSTM training loop with GPU support, early stopping, and evaluation.
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score

from app.config import settings
from app.models.lstm_model import StockLSTM

logger = logging.getLogger(__name__)


def _get_device() -> torch.device:
    """Auto-detect best available device."""
    if torch.cuda.is_available():
        device = torch.device("cuda")
        logger.info(f"Using GPU: {torch.cuda.get_device_name(0)}")
    else:
        device = torch.device("cpu")
        logger.info("Using CPU for training")
    return device


class LSTMTrainer:
    """Handles LSTM training, evaluation, and model persistence."""

    def __init__(self, category: str):
        self.category = category
        self.model: Optional[StockLSTM] = None
        self.device = _get_device()
        self.training_metrics: dict = {}

    def train(
        self,
        X_train: np.ndarray,
        y_class_train: np.ndarray,
        y_reg_train: Optional[np.ndarray],
        X_val: np.ndarray,
        y_class_val: np.ndarray,
        y_reg_val: Optional[np.ndarray],
    ) -> dict:
        """
        Train the LSTM model.

        Args:
            X_train: (n_train, seq_len, n_features)
            y_class_train: (n_train,) binary labels
            y_reg_train: (n_train,) forward return values (optional)
            X_val: (n_val, seq_len, n_features)
            y_class_val: (n_val,) binary labels
            y_reg_val: (n_val,) forward return values (optional)

        Returns:
            dict with training metrics
        """
        n_features = X_train.shape[2]

        self.model = StockLSTM(
            input_size=n_features,
            hidden_size_1=settings.lstm_hidden_size_1,
            hidden_size_2=settings.lstm_hidden_size_2,
            dropout=settings.lstm_dropout,
        ).to(self.device)

        # Build DataLoaders
        train_loader = self._make_loader(X_train, y_class_train, y_reg_train, shuffle=True)
        val_loader = self._make_loader(X_val, y_class_val, y_reg_val, shuffle=False)

        # Loss functions
        bce_loss = nn.BCELoss()
        mse_loss = nn.MSELoss()
        has_regression = y_reg_train is not None

        # Optimizer and scheduler
        optimizer = torch.optim.Adam(self.model.parameters(), lr=settings.lstm_learning_rate)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=5, min_lr=1e-6
        )

        # Training loop with early stopping
        best_val_loss = float("inf")
        best_model_state = None
        patience_counter = 0
        epoch_history = []

        start_time = time.time()

        for epoch in range(settings.lstm_epochs):
            # Train
            self.model.train()
            train_loss_total = 0.0
            train_batches = 0

            for batch in train_loader:
                if has_regression:
                    X_b, y_cls_b, y_reg_b = batch
                    X_b = X_b.to(self.device)
                    y_cls_b = y_cls_b.to(self.device)
                    y_reg_b = y_reg_b.to(self.device)
                else:
                    X_b, y_cls_b = batch
                    X_b = X_b.to(self.device)
                    y_cls_b = y_cls_b.to(self.device)

                optimizer.zero_grad()
                prob, return_pct = self.model(X_b)

                loss = bce_loss(prob.squeeze(), y_cls_b)
                if has_regression:
                    loss = loss + 0.5 * mse_loss(return_pct.squeeze(), y_reg_b)

                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
                optimizer.step()

                train_loss_total += loss.item()
                train_batches += 1

            avg_train_loss = train_loss_total / max(train_batches, 1)

            # Validate
            val_loss, val_metrics = self._evaluate(val_loader, bce_loss, mse_loss, has_regression)
            scheduler.step(val_loss)

            epoch_history.append({
                "epoch": epoch + 1,
                "train_loss": round(avg_train_loss, 4),
                "val_loss": round(val_loss, 4),
                "val_auc": round(val_metrics.get("auc", 0), 4),
            })

            if (epoch + 1) % 10 == 0 or epoch == 0:
                logger.info(
                    f"LSTM {self.category} epoch {epoch + 1}/{settings.lstm_epochs}: "
                    f"train_loss={avg_train_loss:.4f} val_loss={val_loss:.4f} "
                    f"val_auc={val_metrics.get('auc', 0):.3f}"
                )

            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_model_state = {k: v.cpu().clone() for k, v in self.model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= settings.lstm_patience:
                    logger.info(f"Early stopping at epoch {epoch + 1}")
                    break

        elapsed = time.time() - start_time

        # Restore best model
        if best_model_state is not None:
            self.model.load_state_dict(best_model_state)
            self.model.to(self.device)

        # Final evaluation on validation set
        final_loss, final_metrics = self._evaluate(val_loader, bce_loss, mse_loss, has_regression)

        metrics = {
            "category": self.category,
            "auc": final_metrics.get("auc", 0),
            "precision": final_metrics.get("precision", 0),
            "recall": final_metrics.get("recall", 0),
            "f1": final_metrics.get("f1", 0),
            "val_loss": round(final_loss, 4),
            "best_epoch": len(epoch_history) - patience_counter,
            "total_epochs": len(epoch_history),
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "training_time_sec": round(elapsed, 1),
            "device": str(self.device),
        }

        self.training_metrics = metrics

        logger.info(
            f"LSTM {self.category}: AUC={metrics['auc']:.3f} "
            f"P={metrics['precision']:.3f} R={metrics['recall']:.3f} "
            f"F1={metrics['f1']:.3f} ({metrics['total_epochs']} epochs, {elapsed:.1f}s)"
        )
        return metrics

    def _make_loader(
        self,
        X: np.ndarray,
        y_class: np.ndarray,
        y_reg: Optional[np.ndarray],
        shuffle: bool,
    ) -> DataLoader:
        """Create a DataLoader from numpy arrays."""
        tensors = [
            torch.FloatTensor(X),
            torch.FloatTensor(y_class),
        ]
        if y_reg is not None:
            tensors.append(torch.FloatTensor(y_reg))

        dataset = TensorDataset(*tensors)
        return DataLoader(
            dataset,
            batch_size=settings.lstm_batch_size,
            shuffle=shuffle,
            num_workers=0,
            pin_memory=self.device.type == "cuda",
        )

    @torch.no_grad()
    def _evaluate(
        self,
        loader: DataLoader,
        bce_loss: nn.Module,
        mse_loss: nn.Module,
        has_regression: bool,
    ) -> tuple[float, dict]:
        """Evaluate model on a DataLoader. Returns (loss, metrics_dict)."""
        self.model.eval()
        total_loss = 0.0
        n_batches = 0
        all_probs = []
        all_labels = []

        for batch in loader:
            if has_regression:
                X_b, y_cls_b, y_reg_b = batch
                X_b = X_b.to(self.device)
                y_cls_b = y_cls_b.to(self.device)
                y_reg_b = y_reg_b.to(self.device)
            else:
                X_b, y_cls_b = batch
                X_b = X_b.to(self.device)
                y_cls_b = y_cls_b.to(self.device)

            prob, return_pct = self.model(X_b)
            loss = bce_loss(prob.squeeze(), y_cls_b)
            if has_regression:
                loss = loss + 0.5 * mse_loss(return_pct.squeeze(), y_reg_b)

            total_loss += loss.item()
            n_batches += 1

            all_probs.extend(prob.squeeze().cpu().numpy().tolist())
            all_labels.extend(y_cls_b.cpu().numpy().tolist())

        avg_loss = total_loss / max(n_batches, 1)

        # Compute classification metrics
        probs = np.array(all_probs)
        labels = np.array(all_labels)
        preds = (probs >= 0.5).astype(int)

        metrics = {}
        try:
            metrics["auc"] = float(roc_auc_score(labels, probs))
        except ValueError:
            metrics["auc"] = 0.0
        metrics["precision"] = float(precision_score(labels, preds, zero_division=0))
        metrics["recall"] = float(recall_score(labels, preds, zero_division=0))
        metrics["f1"] = float(f1_score(labels, preds, zero_division=0))

        return avg_loss, metrics

    def save(self, path: Path):
        """Save model state dict."""
        if self.model is None:
            raise RuntimeError("No model to save")
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.cpu().state_dict(), str(path))
        self.model.to(self.device)
        logger.info(f"Saved LSTM model: {path}")

    def save_metadata(self, path: Path):
        """Save training metadata."""
        metadata = {
            "category": self.category,
            "metrics": self.training_metrics,
            "config": {
                "hidden_size_1": settings.lstm_hidden_size_1,
                "hidden_size_2": settings.lstm_hidden_size_2,
                "dropout": settings.lstm_dropout,
                "sequence_length": settings.lstm_sequence_length,
                "batch_size": settings.lstm_batch_size,
                "learning_rate": settings.lstm_learning_rate,
                "epochs": settings.lstm_epochs,
                "patience": settings.lstm_patience,
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        logger.info(f"Saved LSTM metadata: {path}")
