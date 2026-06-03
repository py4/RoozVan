# Project
Target audience is Iranian diaspora living in Vancouver, BC. We read recent news from news sources and find relevents news. Then we use generative AI to create instagram-friendly post for Iranian community. Things like new Vancouver laws, or a relevant immigration news or etc.

# Pipeline (in the end)
sources -> recent news extraction -> score -> rank -> dedup -> select -> generate image with generative ai with Farsi content -> generate readable, instagram friendly caption with Farsi -> suggest in Terminal so i can choose 

# Version Control
Always break big changes into smaller readable commits and make sure your changes are commited and push to git
Do not commit generated live artifacts such as ranked_live.json or generated image outputs. These files can be regenerated and should stay out of commits unless explicitly requested.
