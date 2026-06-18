// A simple request-based authorizer example to demonstrate how to use request 
// parameters to allow or deny a request. In this example, a request is  
// authorized if the client-supplied HeaderAuth1 header, QueryString1
// query parameter, and stage variable of StageVar1 all match
// specified values of 'headerValue1', 'queryValue1', and 'stageValue1',
// respectively.
    
export const handler = function(event, context, callback) {
    // DEMO CHECK: Remove this block and replace hardcoded values with Secrets Manager in production
    if (!process.env.AUTH_SECRET_ARN) {
        console.warn('WARNING: Using hardcoded demo credentials. Set AUTH_SECRET_ARN env var for production.');
    }

    console.log('Received event:', JSON.stringify(event, null, 2));
    
    // Retrieve request parameters from the Lambda function input:
    var headers = event.headers;
    var queryStringParameters = event.queryStringParameters;
    var pathParameters = event.pathParameters;
    var stageVariables = event.stageVariables;
        
    // Parse the input for the parameter values
    var tmp = event.methodArn.split(':');
    var apiGatewayArnTmp = tmp[5].split('/');
    var awsAccountId = tmp[4];
    var region = tmp[3];
    var restApiId = apiGatewayArnTmp[0];
    var stage = apiGatewayArnTmp[1];
    var method = apiGatewayArnTmp[2];
    var resource = '/'; // root resource
    if (apiGatewayArnTmp[3]) {
        resource += apiGatewayArnTmp[3];
    }
        
    // Perform authorization to return the Allow policy for correct parameters and 
    // the 'Unauthorized' error, otherwise.
     
    // API Gateway lowercases header keys in REQUEST authorizer events
    var headerAuth = headers.headerauth1 || headers.HeaderAuth1;

    // Validate required parameters exist
    if (!queryStringParameters || !stageVariables) {
        callback(null, generateDeny('me', event.methodArn));
        return;
    }

    // WARNING: These hardcoded values are for demo only. In production, retrieve
    // credentials from AWS Secrets Manager or environment variables. See:
    // https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html
    if (headerAuth === "headerValue1"
        && queryStringParameters.QueryString1 === "queryValue1"
        && stageVariables.StageVar1 === "stageValue1") {
        callback(null, generateAllow('me', event.methodArn));
    }  else {
        callback(null, generateDeny('me', event.methodArn));
    }
}
     
// Help function to generate an IAM policy
var generatePolicy = function(principalId, effect, resource) {
    // Required output:
    var authResponse = {};
    authResponse.principalId = principalId;
    if (effect && resource) {
        var policyDocument = {};
        policyDocument.Version = '2012-10-17'; // default version
        policyDocument.Statement = [];
        var statementOne = {};
        statementOne.Action = 'execute-api:Invoke'; // default action
        statementOne.Effect = effect;
        statementOne.Resource = resource;
        policyDocument.Statement[0] = statementOne;
        authResponse.policyDocument = policyDocument;
    }
    // Optional output with custom properties of the String, Number or Boolean type.
    authResponse.context = {
        "stringKey": "stringval",
        "numberKey": 123,
        "booleanKey": true
    };
    return authResponse;
}
     
var generateAllow = function(principalId, resource) {
    return generatePolicy(principalId, 'Allow', resource);
}
     
var generateDeny = function(principalId, resource) {
    return generatePolicy(principalId, 'Deny', resource);
}
