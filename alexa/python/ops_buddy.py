import os
import json
import boto3
import time
import requests
import pyotp
import logging
import random

from datetime import datetime
from requests.exceptions import HTTPError
from requests.exceptions import ConnectionError

from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_core.handler_input import HandlerInput

from ask_sdk_model.ui import StandardCard
from ask_sdk_model.ui import SimpleCard

from ask_sdk_model.interfaces.display import (
    ImageInstance, Image, RenderTemplateDirective, ListTemplate1,
    BackButtonBehavior, ListItem, BodyTemplate2, BodyTemplate1)

sb = SkillBuilder()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

authorized_users = {}
authorized_users[482] = "UU7SVR3XXVDSF7WQ"
authorized_users[738] = "U6VYRDPQZ5B3V2MW"
authorized_users[351] = "6GQFRWG6VRQ7OSKX"

class PipelineExecutionSummary:
    def __init__(self):
        self.pipelineExecutionId = None
        self.status = None
        self.startTime = None
        self.lastUpdateTime = None
        self.sourceRevisions = []
        self.trigger = None

class SourceRevision:
    def __init__(self):
        self.actionName = None
        self.revisionId = None
        self.revisionSummary = None
        self.revisionUrl = None

class PipelineTrigger:
    def __init__(self):
        self.triggerType = None
        self.triggerDetail = None

class User:
    def __init__(self):
        self.userId = None
        self.name = None
        self.secret_key = None

# Debug helper function to write object into Json and handle datetimes
def serialize(obj):
    if isinstance(obj, datetime):
        return str(obj)
    return obj.__dict__

# Helper function to print json in an easy to read format
def print_json(json_string):
    print(json.dumps(json_string,sort_keys=True,indent = 4,default=serialize))

class LaunchRequestHandler(AbstractRequestHandler):
    """Handler for Skill Launch."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        introduction_speech = [
            "Hey, I'm Ops Buddy. What can I do for you?",
            "Ops Buddy here, What do you need?",
            "Hey there, what can I help you with?",
            "Hey you're friendly neighborhood Ops Buddy here? What can I do for you today?",
            "Hi I am ops buddy, you're personal ops assistant. How can I help you?",
            "Yeah yeah, I'm ops buddy, blah blah blah, what do you want?"
        ]

        card_text = "Available Operations\n- Site Health Check \n- Last Deployment Info \n- Deploy to Production"
        
        # Randomly get an introduction for the list of possibles, this helps to make the app less repetative and more engaging
        speech_selection = random.randint(0,len(introduction_speech))
        speech_text = introduction_speech[speech_selection]

        # Build repsonse to send back to Alexa
        handler_input.response_builder.speak(speech_text).set_card(StandardCard("Ops Buddy",card_text)).set_should_end_session(False)

        return handler_input.response_builder.response

class DeployProdIntentHandler(AbstractRequestHandler):
    """Handler for DeployProd Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("DeployProdIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        # Extract User Input
        slots = handler_input.request_envelope.request.intent.slots
        user_id = int(slots.get("user_id").value)
        passcode = slots.get("passcode").value

        # Print info to logs for debugging purposes
        print("Deploy Production")
        print(f"UserID: {user_id}")
        print(f"Passcode: {passcode}")

        # Get the pipeline name from the environment variables
        pipeline_name = os.getenv("pipeline_name")
        
        # Trigger the Deployment if auth passes
        pipeline_execution_id = self.trigger_deployment(pipeline_name,user_id,passcode)

        # Generate Response for Deployment Status
        if pipeline_execution_id:

            speech_text = "<speak>Deployment Approved. Triggering the deployment now.<break time=\"1s\"/>Is there anything else I can do for you?</speak>"
            card_text = f"Deployment Approved\nPipeline Execution ID: {pipeline_execution_id}"

            handler_input.response_builder.speak(speech_text).set_card(StandardCard("Production Deployment Status",card_text)).set_should_end_session(False)

            print("Deployment Approved")
        else:
            speech_text = "<speak>Invalid Authorization. Deployment Canceled.<break time=\"1s\"/>Is there anything else I can do for you?</speak>"
            card_text = f"Deployment Canceled\nAuthorization Failure"

            handler_input.response_builder.speak(speech_text).set_card(SimpleCard("Production Deployment Status", card_text)).set_should_end_session(False)

            print("Deployment Canceled")
        
        # Return the response
        return handler_input.response_builder.response

    def trigger_deployment(self,pipeline_name,user_id,passcode):

        pipeline_execution_id = None

        if pipeline_name is None:
            print("No Pipeline Name was provided")
            return None

        # Determine if a deployment has been authorized
        deployment_authorized = self.verify_passcode(user_id,passcode)

        # If the user is authorized to deploy, deploy site
        if deployment_authorized:
            print(f"User {user_id} has been authenticated and triggered a deployment")

            # Generate Codepipeline client
            client = boto3.client('codepipeline')

            # Trigger Deployment
            response = client.start_pipeline_execution(
                name=pipeline_name
            )
            
            # Get the pipeline execution id
            pipeline_execution_id = response.get("pipelineExecutionId")
        else:
            print(f"User {user_id} attempted to trigger a deployment but failed authentication")

        # If a deployment has been triggered, return the execution id otherwise return None
        return pipeline_execution_id

    # Verify a OTP for a specific user
    def verify_passcode(self,userid,passcode):
        
        # Get Secret Key by UserId
        secret_key = authorized_users.get(userid)

        # Ensure a secret key was retrieved
        if secret_key == None:
            print("The provided user id was not found. Authorization failed.")
            return False

        # Create TOTP Object
        totp = pyotp.TOTP(secret_key)

        # Verify TOTP Code
        return totp.verify(passcode)

class HealthCheckIntentHandler(AbstractRequestHandler):
    """Handler for HealthCheck Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("HealthCheckIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        print("Executing Healthcheck Intent")

        # Get website url from environment variables
        website_url = os.getenv("website_url")

        # Call the website to determine the HTTP status code it returns
        site_healthy,status_code = self.get_website_status(website_url)
        
        # Print Info to logging for debugging
        print(f"Website Url: {website_url}")
        print(f"Site Health Status : {site_healthy}")
        print(f"Site Health Status Code: {status_code}")

        # Depending on the health status of the site return the proper message to the user
        if site_healthy:

            reprompt = "What else can I do for you?"
            card_text = speech_text = f"The site is healthy and returned an HTTP status code of {str(status_code)}."
            speech_text = f"<speak>The site is healthy and returned an HTTP status code of {str(status_code)}. <break time=\"1s\"/>Is there anything else I can do for you?</speak>"

            handler_input.response_builder.speak(speech_text).ask(reprompt).set_card(SimpleCard("Health Check", card_text)).set_should_end_session(False)
        elif site_healthy and status_code:
            
            reprompt = "What else can I do for you?"
            card_text =f"The site is unhealthy and returned an HTTP status code of {str(status_code)}."
            speech_text =f"<speak>The site is unhealthy and returned an HTTP status code of {str(status_code)}.<break time=\"1s\"/>Is there anything else I can do for you?</speak>"

            handler_input.response_builder.speak(speech_text).ask(reprompt).set_card(SimpleCard("Health Check", card_text)).set_should_end_session(False)
        else:
            
            reprompt = "What else can I do for you?"
            card_text ="There was an issue when I attempted to reach the site"
            speech_text ="<speak>There was an issue when I attempted to reach the site.<break time=\"1s\"/>Is there anything else I can do for you?</speak>"

            handler_input.response_builder.speak(speech_text).ask(reprompt).set_card(SimpleCard("Health Check", card_text)).set_should_end_session(False)

        return handler_input.response_builder.response
    
    # Get website health check
    def get_website_status(self,url):
        status = None
        status_code = None
        try:
            response = requests.get(url)
            if response.status_code == 200:
                status = True
                status_code = response.status_code
            else:
                status = False
                status_code = response.status_code
        except:
            status = False
            
        return status,status_code

class LastDeploymentInfoIntent(AbstractRequestHandler):
    """Handler for retriving info about the last deployment """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("LastDeploymentInfoIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        print("Executing Last Deployment Info Intent")

        # Get pipeline name from environment variables
        pipeline_name = os.getenv("pipeline_name")

        print(f"Pipeline Name: {pipeline_name}")
        pipeline_executions = self.get_pipeline_executions(pipeline_name)

        # Grab the latest execution, the response from AWS appears to be sorted from newest to oldest
        lastest_pipeline_execution = pipeline_executions[0]

        # Get Deployment times and format them to the desired format that Alexa will interpt
        start_time = lastest_pipeline_execution.startTime.strftime("%I:%M%p")
        start_date = lastest_pipeline_execution.startTime.strftime("%Y%m%d")
        finish_time = lastest_pipeline_execution.lastUpdateTime.strftime("%I:%M%p")
        finish_date = lastest_pipeline_execution.lastUpdateTime.strftime("%Y%m%d")

        start_datetime = lastest_pipeline_execution.startTime.strftime("%m/%d/%Y %I:%M %p")
        finish_datetime = lastest_pipeline_execution.lastUpdateTime.strftime("%m/%d/%Y %I:%M %p")

        # Create Speech and Card Text
        reprompt = "What else can I do for you?"
        speech_text = f"<speak>The last deployment {lastest_pipeline_execution.status}. It was started at {start_time} UTC on <say-as interpret-as=\"date\">{start_date}</say-as> and was last updated at {finish_time} UTC on <say-as interpret-as=\"date\">{finish_date}</say-as>.<break time=\"1s\"/>Is there anything else I can do for you?</speak>"
        card_text = f"Deployment ID: {lastest_pipeline_execution.pipelineExecutionId}\nStatus: {lastest_pipeline_execution.status}\nStart Time: {start_datetime} UTC\nLast Update: {finish_datetime} UTC"

        # Build repsonse to send back to Alexa
        handler_input.response_builder.speak(speech_text).ask(reprompt).set_card(StandardCard("Last Deployment Info", card_text)).set_should_end_session(False)

        return handler_input.response_builder.response

    # Get the pipeline executions
    def get_pipeline_executions(self,pipeline_name):
        
        pipeline_execution_summaries = []
        client = boto3.client('codepipeline')
        
        response = client.list_pipeline_executions(
            pipelineName=pipeline_name,
            maxResults=1,
        )

        for item in response.get("pipelineExecutionSummaries"):
            pipeline_execution_summaries.append(self.parse_pipeline_execution(item))

        return pipeline_execution_summaries

    # Parse pipeline info
    def parse_pipeline_execution(self,response_item):

        # Parse Pipeline Execution Summary Info
        pes = PipelineExecutionSummary()
        pes.pipelineExecutionId = response_item.get("pipelineExecutionId")
        pes.status = response_item.get("status")
        pes.startTime = response_item.get("startTime")
        pes.lastUpdateTime = response_item.get("lastUpdateTime")

        # Parse Source Revisions
        for sr in response_item.get("sourceRevisions"):
            temp = SourceRevision()
            temp.actionName = sr.get("actionName")
            temp.revisionId = sr.get("revisionId")
            temp.revisionSummary = sr.get("revisionSummary")
            temp.revisionUrl = sr.get("revisionUrl")

            # Add to the summary list
            pes.sourceRevisions.append(temp)

        # Parse Trigger
        trigger = PipelineTrigger()
        trigger.triggerType = response_item.get("triggerType")
        trigger.triggerDetail = response_item.get("triggerDetail")

        # Add triger info to the summary object
        pes.trigger = trigger

        return pes

class HelpIntentHandler(AbstractRequestHandler):
    """Handler for Help Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        reprompt = "What else can I do for you?"
        card_text = "Available Operations\n- Site Health Check \n- Last Deployment Info \n- Deploy to Production"
        speech_text = "<speak>You can ask me to check the health of your site, get information about the last deployment or even deploy to production.<break time=\"1s\"/>What can I do for you?</speak>"

        handler_input.response_builder.speak(speech_text).ask(reprompt).set_card(SimpleCard("What can I do?", card_text)).set_should_end_session(False)
        return handler_input.response_builder.response

class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Single handler for Cancel and Stop Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.CancelIntent")(handler_input) or
                is_intent_name("AMAZON.StopIntent")(handler_input) or
                is_intent_name("AMAZON.NoIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = "Goodbye!"

        handler_input.response_builder.speak(speech_text)
        return handler_input.response_builder.response

class FallbackIntentHandler(AbstractRequestHandler):
    """
    This handler will not be triggered except in supported locales,
    so it is safe to deploy on any locale.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech_text = ("I'm not sure what you were trying to do. Could you please try again.")
        reprompt = "What can I do for you?"

        handler_input.response_builder.speak(speech_text).ask(reprompt)

        return handler_input.response_builder.response

class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handler for Session End."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        return handler_input.response_builder.response

class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Catch all exception handler, log exception and
    respond with custom message.
    """
    def can_handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> bool
        return True

    def handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> Response
        logger.error(exception, exc_info=True)

        speech = "Sorry, there was some problem. Please try again!!"
        handler_input.response_builder.speak(speech).ask(speech)

        return handler_input.response_builder.response

# Add methods to the skill builder instance
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_request_handler(DeployProdIntentHandler())
sb.add_request_handler(HealthCheckIntentHandler())
sb.add_request_handler(LastDeploymentInfoIntent())

sb.add_exception_handler(CatchAllExceptionHandler())

handler = sb.lambda_handler()