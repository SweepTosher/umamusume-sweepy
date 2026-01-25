import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import cv2
import os

class DigitCNN(nn.Module):
    def __init__(self):
        super(DigitCNN, self).__init__()
        self.conv1 = nn.Conv2d(1, 32, 3, padding=1)
        self.conv2 = nn.Conv2d(32, 64, 3, padding=1)
        self.conv3 = nn.Conv2d(64, 64, 3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        self.fc1 = nn.Linear(64 * 4 * 3, 128)
        self.fc2 = nn.Linear(128, 10)
        self.dropout = nn.Dropout(0.25)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = self.pool(F.relu(self.conv3(x)))
        x = x.view(-1, 64 * 4 * 3)
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        return x

class DigitClassifier:
    def __init__(self, model_path=None):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = DigitCNN().to(self.device)
        self.model.eval()
        if model_path and os.path.exists(model_path):
            self.model.load_state_dict(torch.load(model_path, map_location=self.device))

    def preprocess(self, img):
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.resize(img, (24, 32))
        img = img.astype(np.float32) / 255.0
        img = torch.from_numpy(img).unsqueeze(0).unsqueeze(0)
        return img.to(self.device)

    def predict(self, img):
        with torch.no_grad():
            x = self.preprocess(img)
            output = self.model(x)
            probs = F.softmax(output, dim=1)
            pred = torch.argmax(probs, dim=1).item()
            conf = probs[0, pred].item()
        return pred, conf

    def predict_batch(self, images):
        if not images:
            return []
        with torch.no_grad():
            batch = torch.cat([self.preprocess(img) for img in images], dim=0)
            output = self.model(batch)
            probs = F.softmax(output, dim=1)
            preds = torch.argmax(probs, dim=1).cpu().numpy()
            confs = probs[torch.arange(len(preds)), preds].cpu().numpy()
        return list(zip(preds.tolist(), confs.tolist()))

    def save(self, path):
        torch.save(self.model.state_dict(), path)

    def load(self, path):
        self.model.load_state_dict(torch.load(path, map_location=self.device))
        self.model.eval()
