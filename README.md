# Email Analysis and Management System

An intelligent email analysis and management system that processes emails, extracts insights, and manages reminders.

## Features

- Email reading and processing
- GPT-powered email analysis
- Founder communication insights
- Reminder management
- Memory storage and retrieval
- Vector search using Pinecone

## Project Structure

```
.
├── core/               # Core functionality
│   ├── mail.py        # Email reading
│   ├── gpt.py         # GPT integration
│   ├── agent.py       # Main agent
│   ├── email_sender.py # Email sending
│   └── __init__.py
├── sentience/         # Memory and analysis
│   ├── memory.py      # Memory management
│   ├── founder.py     # Founder analysis
│   ├── pinecone_client.py  # Vector storage
│   └── __init__.py
├── reminders/         # Reminder management
│   ├── core.py        # Reminder functionality
│   └── __init__.py
├── main.py           # Main entry point
├── config.py         # Configuration
├── requirements.txt  # Dependencies
└── README.md         # Documentation
```

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file with the following variables:
   ```
   # Email configuration
   EMAIL_USER=your_email@gmail.com
   EMAIL_PASS=your_app_password
   IMAP_SERVER=imap.gmail.com

   # OpenAI configuration
   OPENAI_API_KEY=your_openai_api_key
   GPT_MODEL=gpt-4

   # Firebase configuration
   GOOGLE_APPLICATION_CREDENTIALS=path/to/your/firebase-credentials.json

   # Pinecone configuration
   PINECONE_API_KEY=your_pinecone_api_key
   PINECONE_ENVIRONMENT=us-west1-gcp
   PINECONE_INDEX=email-vectors

   # Logging configuration
   LOG_LEVEL=INFO
   ```

3. Run the system:
   ```bash
   python main.py
   ```

## Usage

The system will:
1. Connect to your email account
2. Process unread emails
3. Analyze emails using GPT
4. Extract insights from founder communications
5. Create reminders for action items
6. Store memories for future reference
7. Enable vector search for similar emails

## Development

- Use Python 3.8 or higher
- Follow PEP 8 style guide
- Add tests for new functionality
- Update documentation as needed

## License

MIT License 