"""
LSTM model architecture for temporal stock signal prediction.
"""
import torch
import torch.nn as nn


class StockLSTM(nn.Module):
    """
    Two-layer LSTM with dual output heads:
    - Classification: probability of profitable trade (sigmoid)
    - Regression: predicted forward return % (linear)
    """

    def __init__(
        self,
        input_size: int = 45,
        hidden_size_1: int = 128,
        hidden_size_2: int = 64,
        dropout: float = 0.3,
    ):
        super().__init__()

        self.lstm1 = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size_1,
            batch_first=True,
            dropout=0,
        )
        self.dropout1 = nn.Dropout(dropout)

        self.lstm2 = nn.LSTM(
            input_size=hidden_size_1,
            hidden_size=hidden_size_2,
            batch_first=True,
            dropout=0,
        )
        self.dropout2 = nn.Dropout(dropout)

        self.dense = nn.Linear(hidden_size_2, 32)
        self.relu = nn.ReLU()

        # Classification head: profitable trade probability
        self.classifier = nn.Linear(32, 1)
        self.sigmoid = nn.Sigmoid()

        # Regression head: predicted return %
        self.regressor = nn.Linear(32, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            x: (batch_size, sequence_length, num_features)

        Returns:
            prob: (batch_size, 1) - probability of profitable trade
            return_pct: (batch_size, 1) - predicted return %
        """
        out, _ = self.lstm1(x)
        out = self.dropout1(out)

        out, _ = self.lstm2(out)
        out = self.dropout2(out)

        # Take the last time step
        out = out[:, -1, :]

        out = self.relu(self.dense(out))

        prob = self.sigmoid(self.classifier(out))
        return_pct = self.regressor(out)

        return prob, return_pct
