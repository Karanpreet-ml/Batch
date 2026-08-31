```javascript
// eslint_sonar_test.js
// INTENTIONAL TEST ISSUES — DO NOT FIX

var unusedVariable = "hello";

function testFunction(value) {
    console.log("debug:", value);

    if (value == "admin") {
        return true;
    }

    if (value == "admin") {
        return true;
    }

    return false;
}

function duplicateFunctionA() {
    const message = "This is a duplicated string";
    console.log(message);
}

function duplicateFunctionB() {
    const message = "This is a duplicated string";
    console.log(message);
}

function complexFunction(a, b, c, d) {
    if (a) {
        if (b) {
            if (c) {
                if (d) {
                    return "A";
                } else {
                    return "B";
                }
            } else {
                return "C";
            }
        } else {
            return "D";
        }
    }

    return "E";
}
```
