import os
import torch
import torch.nn as nn
import joblib
from transformers import BertTokenizer, BertModel
from django.conf import settings

class TripleBERTClassifier(nn.Module):
    def __init__(self, kra_classes, crit_classes, sub_classes):
        super(TripleBERTClassifier, self).__init__()
        self.bert = BertModel.from_pretrained('bert-base-uncased')
        self.kra_classifier = nn.Linear(self.bert.config.hidden_size, kra_classes)
        self.crit_classifier = nn.Linear(self.bert.config.hidden_size, crit_classes)
        self.sub_classifier = nn.Linear(self.bert.config.hidden_size, sub_classes)

    def forward(self, input_ids, attention_mask):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        pooled_output = outputs.pooler_output
        kra_logits = self.kra_classifier(pooled_output)
        crit_logits = self.crit_classifier(pooled_output)
        sub_logits = self.sub_classifier(pooled_output)
        return kra_logits, crit_logits, sub_logits


def load_model_and_encoders():
    try:
        model_path = os.path.join(settings.BASE_DIR, 'api', 'ml_models', 'bert_hierarchical_model.pt')
        kra_encoder_path = os.path.join(settings.BASE_DIR, 'api', 'ml_models', 'kra_encoder.pkl')
        crit_encoder_path = os.path.join(settings.BASE_DIR, 'api', 'ml_models', 'crit_encoder.pkl')
        sub_encoder_path = os.path.join(settings.BASE_DIR, 'api', 'ml_models', 'sub_encoder.pkl')
        tokenizer_path = os.path.join(settings.BASE_DIR, 'api', 'ml_models', 'saved_tokenizer')

        if not all(os.path.exists(p) for p in [model_path, kra_encoder_path, crit_encoder_path, sub_encoder_path, tokenizer_path]):
            raise FileNotFoundError("One or more model/encoder/tokenizer files are missing.")

        kra_encoder = joblib.load(kra_encoder_path)
        crit_encoder = joblib.load(crit_encoder_path)
        sub_encoder = joblib.load(sub_encoder_path)
        tokenizer = BertTokenizer.from_pretrained(tokenizer_path)

        kra_classes = len(kra_encoder.classes_)
        crit_classes = len(crit_encoder.classes_)
        sub_classes = len(sub_encoder.classes_)

        model = TripleBERTClassifier(kra_classes, crit_classes, sub_classes)

        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model.load_state_dict(torch.load(model_path, map_location=device))
        model.to(device)
        model.eval()

        print("Model, encoders, and tokenizer loaded successfully.")
        return model, tokenizer, kra_encoder, crit_encoder, sub_encoder, device

    except Exception as e:
        print(f"Error loading model/encoders/tokenizer: {e}")
        return None, None, None, None, None, None


MODEL, TOKENIZER, KRA_ENCODER, CRIT_ENCODER, SUB_ENCODER, DEVICE = load_model_and_encoders()


def classify_document(text):
    if not MODEL or not TOKENIZER or not KRA_ENCODER or not CRIT_ENCODER or not SUB_ENCODER:
        print("Model components not available.")
        return {"primary_kra": "Unknown", "confidence": 0, "criterion": "N/A", "sub_criterion": "N/A"}

    try:
        inputs = TOKENIZER(
            text,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=512
        )
        input_ids = inputs["input_ids"].to(DEVICE)
        attention_mask = inputs["attention_mask"].to(DEVICE)

        with torch.no_grad():
            kra_logits, crit_logits, sub_logits = MODEL(input_ids, attention_mask)

            kra_pred_idx = torch.argmax(kra_logits, dim=1).item()
            crit_pred_idx = torch.argmax(crit_logits, dim=1).item()
            sub_pred_idx = torch.argmax(sub_logits, dim=1).item()

            kra_probs = torch.softmax(kra_logits, dim=1)
            crit_probs = torch.softmax(crit_logits, dim=1)
            sub_probs = torch.softmax(sub_logits, dim=1)

            kra_confidence = float(kra_probs[0][kra_pred_idx].item()) * 100
            crit_confidence = float(crit_probs[0][crit_pred_idx].item()) * 100
            sub_confidence = float(sub_probs[0][sub_pred_idx].item()) * 100

        kra_label = KRA_ENCODER.inverse_transform([kra_pred_idx])[0]
        crit_label = CRIT_ENCODER.inverse_transform([crit_pred_idx])[0]
        sub_label = SUB_ENCODER.inverse_transform([sub_pred_idx])[0]

        return {
            'primary_kra': kra_label,
            'confidence': round(kra_confidence, 1),
            'criterion': crit_label,
            'sub_criterion': sub_label,
            'explanation': f"Document classified as '{kra_label}' with {round(kra_confidence, 1)}% confidence."
        }

    except Exception as e:
        print(f"Error during document classification: {e}")
        return {"primary_kra": "Error", "confidence": 0, "criterion": "N/A", "sub_criterion": "N/A"}