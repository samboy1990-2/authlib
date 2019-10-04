import os
import time
import binascii
from authlib.consts import default_json_headers
from authlib.common.security import generate_token
from authlib.jose import jwt
from authlib.jose.errors import JoseError
from ..rfc6749 import AccessDeniedError, InvalidRequestError
from ..rfc6749.util import scope_to_list
from .claims import ClientMetadataClaims
from .errors import (
    InvalidClientMetadataError,
    UnapprovedSoftwareStatementError,
    InvalidSoftwareStatementError,
)


class ClientRegistrationEndpoint(object):
    """The client registration endpoint is an OAuth 2.0 endpoint designed to
    allow a client to be registered with the authorization server.
    """
    ENDPOINT_NAME = 'client_registration'

    claims_class = ClientMetadataClaims
    enable_software_statement = False

    def __init__(self, server):
        self.server = server

    def __call__(self, request):
        return self.create_registration_response(request)

    def create_registration_response(self, request):
        user = self.authenticate_user(request)
        if not user:
            raise AccessDeniedError()

        request.user = user

        client_metadata = self.extract_client_metadata(request)
        client_info = self.generate_client_info()
        body = {}
        body.update(client_metadata)
        body.update(client_info)
        self.save_client(client_info, client_metadata, user)
        return 201, body, default_json_headers

    def extract_client_metadata(self, request):
        if not request.data:
            raise InvalidRequestError()

        json_data = request.data.copy()
        software_statement = json_data.pop('software_statement', None)
        if software_statement and self.enable_software_statement:
            data = self.extract_software_statement(software_statement, request)
            json_data.update(data)

        options = self.get_claims_options()
        claims = self.claims_class(json_data, {}, options, self.server.metadata)
        try:
            claims.validate()
        except JoseError as error:
            raise InvalidClientMetadataError(error.description)
        return claims

    def extract_software_statement(self, software_statement, request):
        key = self.resolve_public_key(request)
        if not key:
            raise UnapprovedSoftwareStatementError()

        try:
            claims = jwt.decode(software_statement, key)
            # there is no need to validate claims
            return claims
        except JoseError:
            raise InvalidSoftwareStatementError()

    def get_claims_options(self):
        """Generate claims options validation from Authorization Server metadata."""
        metadata = self.server.metadata
        if not metadata:
            return {}

        scopes_supported = metadata.get('scopes_supported')
        response_types_supported = metadata.get('response_types_supported')
        grant_types_supported = metadata.get('grant_types_supported')
        auth_methods_supported = metadata.get('token_endpoint_auth_methods_supported')
        options = {}
        if scopes_supported is not None:
            scopes_supported = set(scopes_supported)

            def _validate_scope(value):
                if not value:
                    return True
                scopes = set(scope_to_list(value))
                return scopes_supported.issuperset(scopes)

            options['scope'] = {'validate': _validate_scope}

        if response_types_supported is not None:
            response_types_supported = set(response_types_supported)

            def _validate_response_types(value):
                return response_types_supported.issuperset(set(value))

            options['response_types'] = {'validate': _validate_response_types}

        if grant_types_supported is not None:
            grant_types_supported = set(grant_types_supported)

            def _validate_grant_types(value):
                return grant_types_supported.issuperset(set(value))

            options['grant_types'] = {'validate': _validate_grant_types}

        if auth_methods_supported is not None:
            options['token_endpoint_auth_method'] = {'values': auth_methods_supported}

        return options

    def generate_client_info(self):
        # https://tools.ietf.org/html/rfc7591#section-3.2.1
        client_id = self.generate_client_id()
        client_secret = self.generate_client_secret()
        client_id_issued_at = int(time.time())
        client_secret_expires_at = 0
        return dict(
            client_id=client_id,
            client_secret=client_secret,
            client_id_issued_at=client_id_issued_at,
            client_secret_expires_at=client_secret_expires_at,
        )

    def create_endpoint_request(self, request):
        return self.server.create_json_request(request)

    def generate_client_id(self):
        return generate_token(42)

    def generate_client_secret(self):
        return binascii.hexlify(os.urandom(24)).decode('ascii')

    def authenticate_user(self, request):
        """Authenticate current user who is requesting to register a client.
        Developers MUST implement this method in subclass::

            def authenticate_user(self, request):
                auth = request.headers.get('Authorization')
                return get_user_by_auth(auth)

        :return: user instance
        """
        raise NotImplementedError()

    def resolve_public_key(self, request):
        """Resolve a public key for decoding ``software_statement``. If
        ``enable_software_statement=True``, developers MUST implement this
        method in subclass::

            def resolve_public_key(self, request):
                return get_public_key_from_user(request.user)

        :return: JWK or Key string
        """
        raise NotImplementedError()

    def save_client(self, client_info, client_metadata, user):
        """Save client into database. Developers MUST implement this method
        in subclass::

            def save_client(self, client_info, client_metadata, user):
                client = OAuthClient(
                    user_id=user.id,
                    client_id=client_info['client_id'],
                    client_secret=client_info['client_secret'],
                    ...
                )
                client.save()
        """
        raise NotImplementedError()
